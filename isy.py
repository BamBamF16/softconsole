import collections
import isycodes
import historybuffer

import xmltodict
import requests, time
import config
import debug
import exitutils
import utilities
import logsupport
from logsupport import ConsoleWarning, ConsoleError, ConsoleDetailHigh
import sys
import errno
import isyeventmonitor, threadmanager
from stores import valuestore, isyvarssupport

class CommsError(Exception): pass


class ISYNode(object):
	def __init__(self, Hub,name):
		self.Hub = Hub
		self.name = name
		self.fullname = ""

class TreeItem(ISYNode):
	"""
	Provides the graph structure for the ISY representation.  Any ISY node can have a parent and children managed by
	this class.  The class also holds identity information, namely name and addr
	"""

	def __init__(self, hub, name, addr, parentaddr):
		super(TreeItem,self).__init__(hub, name)
		self.address = addr
		self.parent = parentaddr  # replaced by actual obj reference at end of tree build
		self.children = []
		utilities.register_example("TreeItem", self)

	def __repr__(self):
		return 'Tree Item: ' + self.name + '/' + self.address + ' ' + str(len(self.children)) + ' children'


class OnOffItem(ISYNode):
	"""
	Provides command handling for nodes that can be sent on/off faston/fastoff commands.
	"""

	def SendOnOffCommand(self, settoon, presstype):
		selcmd = (('DOF', 'DFOF'), ('DON', 'DFON'))
		debug.debugPrint('ISYdbg', "OnOff sent: ", selcmd[settoon][presstype], ' to ', self.name)
		r = self.Hub.try_ISY_comm('nodes/' + self.address + '/cmd/' + selcmd[settoon][presstype])
		if r == "": # error in comm - fake a response to see unavailable key
			self.Hub.isyEM.FakeNodeChange()

class Folder(TreeItem):
	"""
	Represents and ISY node/scene folder.
	"""

	def __init__(self, hub, flag, name, addr, parenttyp, parentaddr):
		TreeItem.__init__(self, hub, name, addr, parentaddr)
		self.flag = flag
		self.parenttype = parenttyp
		utilities.register_example("Folder", self)

	def __repr__(self):
		return "Folder: " + TreeItem.__repr__(self) + ' flag ' + str(self.flag) + ' parenttyp ' + str(self.parenttype)


class Node(Folder, OnOffItem):
	"""
	Represents and ISY device node.
	"""

	def __init__(self, hub, flag, name, addr, parenttyp, parentaddr, enabled, props):
		Folder.__init__(self, hub, flag, name, addr, parenttyp, parentaddr)
		self.pnode = None  # for things like KPLs
		self.enabled = enabled == "true"
		self.hasstatus = False
		self.devState = -1  # device status reported in the ISY event stream
		# props is either an OrderedDict(@id:ST,@value:val, . . .) or a list of such
		if isinstance(props, collections.OrderedDict):
			props = [props]  # make it a list so below always works
		for item in props:
			if item['@id'] == 'ST':
				self.devState = isycodes._NormalizeState(item['@value'])
				if item['@value'] != ' ':
					self.hasstatus = True
			# no use for nodetype now
			# device class -energy management
			# wattage, dcPeriod
		utilities.register_example("Node", self)

	def __repr__(self):
		return 'Node: ' + Folder.__repr__(self) + 'primary: ' + self.pnode.name


class Scene(TreeItem, OnOffItem):
	"""
	Represents an ISY scene.
	"""

	def __init__(self, hub, flag, name, addr, parenttyp, parent, members):
		"""

		:rtype: Scene
		"""
		TreeItem.__init__(self, hub, name, addr, parent)
		self.flag = flag
		self.parenttype = parenttyp
		# self.devGroup = devGroup
		self.members = members
		self.proxy = ""
		self.obj = None
		utilities.register_example("Scene", self)

	def __repr__(self):
		return "Scene: " + TreeItem.__repr__(self) + ' ' + str(
			len(self.members)) + ' members: ' + self.members.__repr__()


class ProgramFolder(TreeItem):
	"""
	Represents an ISY program folder (ISY keeps the node and program folders separately)
	"""

	def __init__(self, hub, nm, itemid, pid):
		TreeItem.__init__(self, hub, nm, itemid, pid)
		self.status = False
		# not using lastRunTime, lastFinishTime
		utilities.register_example("ProgramFolder", self)

	def __repr__(self):
		return 'ProgFolder: ' + TreeItem.__repr__(self) + ' status ' + str(self.status)


class Program(ProgramFolder):
	"""
	Represents an ISY program and provides command support to issue run commands to it.
	"""

	def __init__(self, hub, nm, itemid, pid):
		ProgramFolder.__init__(self, hub, nm, itemid, pid)
		# not using enabled, runAtStartup,running
		utilities.register_example("Program", self)

	def RunProgram(self):  # for ISY this does a runThen
		debug.debugPrint('ISYdbg', "runThen sent to ", self.name)
		url = self.Hub.ISYprefix + 'programs/' + self.address + '/runThen'
		self.Hub.HBDirect.Entry('Runprog: ' + url)
		_ = self.Hub.ISYrequestsession.get(url)

	def __repr__(self):
		return 'Program: ' + TreeItem.__repr__(self) + ' '


class ISY(object):
	"""
	Representation of an ISY system as a whole and provides roots to its structures
	and useful directories to its nodes/programs.  Provides a debug method to dump the constructed graph.
	"""

	def __init__(self, name, isyaddr, user, pwd):

		if isyaddr == '' or user == '':
			logsupport.Logs.Log("ISY id info missing:  addr: {} user: {}".format(isyaddr, user), severity=ConsoleError)
			raise ValueError

		if isyaddr.startswith('http'):
			self.ISYprefix = isyaddr + '/rest/'
		else:
			self.ISYprefix = 'http://' + isyaddr + '/rest/'
		self.ISYrequestsession = requests.session()
		self.ISYrequestsession.auth = (user, pwd)

		self.name = name
		self.addr = isyaddr
		self.user = user
		self.password = pwd
		self._NodeRoot = Folder(self, 0, '', u'0', 0, u'0') # *root*
		self._ProgRoot = None
		self.NodesByAddr = {}
		self._FoldersByAddr = {'0': self._NodeRoot}
		self._ScenesByAddr = {}
		self._NodesByName = {}
		self._NodesByFullName = {}
		self._ScenesByName = {}
		self._FoldersByName = {}
		self._ProgramFoldersByAddr = {}
		self._ProgramsByAddr = {}
		self._ProgramsByName = {}
		self._ProgramFoldersByName = {}
		self._HubOnline = False
		self.Vars = None
		self.ErrNodes = {}
		self.Busy = 0


		"""
		Build the Folder/Node/Scene tree
		"""
		logsupport.Logs.Log("Create Structure for ISY hub: ", name, ' at ', isyaddr, ' for user ', user)

		trycount = 20
		while True:
			# noinspection PyBroadException
			try:
				r = self.ISYrequestsession.get(self.ISYprefix + 'nodes', verify=False, timeout=5)
				logsupport.Logs.Log('{}: Successful node read: {}'.format(name, r.status_code))
				break
			except:
				# after total power outage ISY is slower to come back than RPi so
				# we wait testing periodically.  Eventually we try rebooting just in case our own network
				# is what is hosed
				trycount -= 1
				if trycount > 0:
					logsupport.Logs.Log('{}:  Hub not responding: '.format(self.name))
					logsupport.Logs.Log('-ISY (nodes): ' + self.ISYprefix)
					time.sleep(15)
				else:
					logsupport.Logs.Log('No ISY response restart (nodes)')
					exitutils.errorexit(exitutils.ERRORPIREBOOT)
					logsupport.Logs.Log('Reached unreachable code! ISY1')

		if r.status_code != 200:
			logsupport.Logs.Log('Hub (' + self.name + ') text response:', severity=ConsoleError)
			logsupport.Logs.Log('-----', severity=ConsoleError)
			logsupport.Logs.Log(r.text, severity=ConsoleError)
			logsupport.Logs.Log('-----', severity=ConsoleError)
			logsupport.Logs.Log('Cannot access ISY - check username/password')
			logsupport.Logs.Log('Status code: ' + str(r.status_code))
			time.sleep(10)
			exitutils.errorexit(exitutils.ERRORDIE)
			logsupport.Logs.Log('Reached unreachable code! ISY2')

		configdict = xmltodict.parse(r.text)['nodes']
		if debug.dbgStore.GetVal('ISYLoad'):
			with open('/home/pi/Console/xml.dmp','r') as f:
				x1 = f.readline().rstrip('\n')
				x2 = f.readline().rstrip('\n')
				x3 = f.readline().rstrip('\n')
				x4 = f.readline().rstrip('\n')
				configdict = xmltodict.parse(x1)['nodes']
		else:
			x2=''
			x3=''
			x4=''

		if debug.dbgStore.GetVal('ISYDump'):
			debug.ISYDump("xml.dmp",r.text,pretty=False,new=True)
			debug.ISYDump("struct.dmp",configdict,new=True)
			debug.ISYDump("isystream.dmp","",pretty=False,new=True)

		for folder in configdict['folder']:
			addr = folder['address']
			parentaddr = str(0)
			ptyp = 3
			if 'parent' in folder:
				ptyp = int(folder['parent']['@type'])
				parentaddr = folder['parent']['#text']
			self._FoldersByAddr[addr] = Folder(self, folder['@flag'], folder['name'], str(addr), ptyp, parentaddr)
		self._LinkChildrenParents(self._FoldersByAddr, self._FoldersByName, self._FoldersByAddr, self.NodesByAddr)

		fixlist = []
		for node in configdict['node']:
			parentaddr = str(0)
			ptyp = 3
			flg = 'unknown'
			nm = 'unknown'
			addr = 'unknown'
			enabld = 'unknown'
			prop = 'unknown'
			pnd = 'unknown'
			if 'parent' in node:
				ptyp = int(node['parent']['@type'])
				parentaddr = node['parent']['#text']
			# noinspection PyBroadException
			try:
				flg = node['@flag']
				nm = node['name']
				addr = node['address']
				enabld = node['enabled']
				pnd = node['pnode']
				prop = node['property']
				n = Node(self, flg, nm, addr, ptyp, parentaddr, enabld, prop)
				fixlist.append((n, pnd))
				self.NodesByAddr[n.address] = n
			except:
				logsupport.Logs.Log("Problem with processing node: ", nm, ' Address: ', str(addr), ' Pnode: ', str(pnd),
								' ', str(flg), '/', str(enabld), '/', repr(prop), severity=ConsoleWarning)
				# for now at least try to avoid nodes without properties which apparently Zwave devices may have
		self._LinkChildrenParents(self.NodesByAddr, self._NodesByName, self._FoldersByAddr, self.NodesByAddr)
		for fixitem in fixlist:
			# noinspection PyBroadException
			try:
				fixitem[0].pnode = self.NodesByAddr[fixitem[1]]
			except:
				logsupport.Logs.Log("Problem with processing node: ", fixitem[1], severity=ConsoleWarning)

		for scene in configdict['group']:
			memberlist = []
			if scene['members'] is not None:
				m1 = scene['members']['link']
				naddr = ''
				# noinspection PyBroadException
				try:
					if isinstance(m1, list):
						for m in m1:
							naddr = m['#text']
							memberlist.append((int(m['@type']), self.NodesByAddr[naddr]))
					else:
						naddr = m1['#text']
						memberlist.append((int(m1['@type']), self.NodesByAddr[naddr]))
				except:
					logsupport.Logs.Log("Error adding member to scene: ", str(scene['name']), ' Node address: ', naddr, severity=ConsoleWarning)
					debug.debugPrint('ISYDump','Scene: ',m1)

				if 'parent' in scene:
					ptyp = int(scene['parent']['@type'])
					p = scene['parent']['#text']
				else:
					ptyp = 0
					p = '0'
				self._ScenesByAddr[scene['address']] = Scene(self, scene['@flag'], scene['name'], str(scene['address']), ptyp,
															 p, memberlist)
			else:
				if scene['name'] not in ('~Auto DR', 'Auto DR'):
					logsupport.Logs.Log('Scene with no members ', scene['name'], severity=ConsoleWarning)
		self._LinkChildrenParents(self._ScenesByAddr, self._ScenesByName, self._FoldersByAddr, self.NodesByAddr)

		self._SetFullNames(self._NodeRoot, "")

		if debug.dbgStore.GetVal('ISYdbg'):
			self.PrintTree(self._NodeRoot, "    ", 'Nodes')

		"""
		Build the Program tree
		"""

		trycount = 20
		while True:
			# noinspection PyBroadException
			try:
				r = self.ISYrequestsession.get(self.ISYprefix + 'programs?subfolders=true', verify=False, timeout=5)
				if r.status_code != 200:
					logsupport.Logs.Log('Hub (' + self.name + ') bad program read' + r.text, severity=ConsoleWarning)
					raise requests.exceptions.ConnectionError  # fake a connection error if we didn't get a good read
				logsupport.Logs.Log('{}: Successful programs read: {}'.format(self.name, r.status_code))
				break
			# except requests.exceptions.ConnectTimeout:
			except:
				# after total power outage ISY is slower to come back than RPi sowait testing periodically.
				# Eventually we try rebooting just in case our own network is what is hosed
				trycount -= 1
				if trycount > 0:
					logsupport.Logs.Log('Hub not responding: ', self.name)
					logsupport.Logs.Log('-ISY(programs): ' + self.ISYprefix)
					time.sleep(15)
				else:
					logsupport.Logs.Log('No ISY response restart (programs)')
					exitutils.errorexit(exitutils.ERRORPIREBOOT)
		configdict = xmltodict.parse(r.text)['programs']['program']
		if debug.dbgStore.GetVal('ISYLoad'):
			configdict = xmltodict.parse(x2)['programs']['program']
		if debug.dbgStore.GetVal('ISYDump'):
			debug.ISYDump("xml.dmp",r.text,pretty=False)
			debug.ISYDump("struct.dmp",configdict)

		for item in configdict:
			if item['@id'] == '0001':
				# Program Root
				self._ProgRoot = ProgramFolder(self, item['name'], '0001', '0001')
				self._ProgramFoldersByAddr['0001'] = self._ProgRoot
			else:
				if item['@folder'] == 'true':
					self._ProgramFoldersByAddr[item['@id']] = ProgramFolder(self, item['name'], item['@id'], item['@parentId'])
				else:
					self._ProgramsByAddr[item['@id']] = Program(self, item['name'], item['@id'], item['@parentId'])
		self._LinkChildrenParents(self._ProgramFoldersByAddr, self._ProgramFoldersByName, self._ProgramFoldersByAddr,
								  self._ProgramsByAddr)
		self._LinkChildrenParents(self._ProgramsByAddr, self._ProgramsByName, self._ProgramFoldersByAddr,
								  self._ProgramsByAddr)

		"""
		Get the variables
		"""
		while True:
			# noinspection PyBroadException
			try:
				r1 = self.ISYrequestsession.get(self.ISYprefix + 'vars/definitions/2', verify=False, timeout=5)
				r2 = self.ISYrequestsession.get(self.ISYprefix + 'vars/definitions/1', verify=False, timeout=5)
				# for some reason var reads seem to typically take longer to complete so to at 5 sec
				if r1.status_code != 200 or r2.status_code != 200:
					logsupport.Logs.Log("Bad ISY var read" + r1.text + r2.text, severity=ConsoleWarning)
					raise requests.exceptions.ConnectionError  # fake connection error on bad read
				logsupport.Logs.Log(
					'{}: Successful variable read: {}/{}'.format(self.name, r1.status_code, r2.status_code))
				break
			except:
				# after total power outage ISY is slower to come back than RPi so we wait testing periodically
				# Eventually we try rebooting just in case our own network is what is hosed
				trycount -= 1
				if trycount > 0:
					logsupport.Logs.Log('Hub not responding: ', self.name)
					logsupport.Logs.Log('-ISY(vars): ' + self.ISYprefix)
					time.sleep(15)
				else:
					logsupport.Logs.Log('No ISY response restart (vars)')
					exitutils.errorexit(exitutils.ERRORPIREBOOT)
					logsupport.Logs.Log('Reached unreachable code! ISY4')

		self.Vars = valuestore.NewValueStore(isyvarssupport.ISYVars(self))
		# noinspection PyBroadException
		try:
			configdictS = xmltodict.parse(r1.text)['CList']['e']
			if debug.dbgStore.GetVal('ISYLoad'):
				configdictS = xmltodict.parse(x3)['CList']['e']
			if debug.dbgStore.GetVal('ISYDump'):
				debug.ISYDump("xml.dmp", r1.text, pretty=False)
				debug.ISYDump("struct.dmp", configdictS)
			for v in configdictS:
				self.Vars.SetVal(('State',v['@name']),None)
				self.Vars.SetAttr(('State',v['@name']),(2,int(v['@id'])))
				self.Vars.AddAlert(('State',v['@name']),self._ISYVarChanged)
		except:
			logsupport.Logs.Log('No state variables defined')
		# noinspection PyBroadException
		try:
			configdictI = xmltodict.parse(r2.text)['CList']['e']
			if debug.dbgStore.GetVal('ISYLoad'):
				configdictI = xmltodict.parse(x4)['CList']['e']
			if debug.dbgStore.GetVal('ISYDump'):
				debug.ISYDump("xml.dmp", r2.text, pretty=False)
				debug.ISYDump("struct.dmp", configdictI)
			for v in configdictI:
				self.Vars.SetVal(('Int',v['@name']),None)
				self.Vars.SetAttr(('Int',v['@name']),(1,int(v['@id'])))
				self.Vars.AddAlert(('Int', v['@name']), self._ISYVarChanged)
		except:
			logsupport.Logs.Log('No integer variables defined')

		'''
		Add command varibles if needed
		'''
		cmdvar = valuestore.InternalizeVarName(self.name+':Int:Command.' + config.hostname.replace('-', '.'))
		self.alertspeclist = {}
		for k in valuestore.ValueStores[self.name].items():
			if k == tuple(cmdvar[1:]):
				self.alertspeclist['RemoteCommands-'+self.name] = {
					'Type': 'VarChange', 'Var': valuestore.ExternalizeVarName(cmdvar), 'Test': 'NE', 'Value': '0',
					'Invoke': 'NetCmd.Command'}
				break

		self.Vars.LockStore()
		utilities.register_example("ISY", self)
		if debug.dbgStore.GetVal('ISYdbg'):
			self.PrintTree(self._ProgRoot, "    ", 'Programs')

		self.HBWS = historybuffer.HistoryBuffer(40, self.name + '-WS')
		self.HBDirect = historybuffer.HistoryBuffer(40, self.name + '-Direct')
		self.isyEM = isyeventmonitor.ISYEventMonitor(self)
		threadmanager.SetUpHelperThread(self.name,self.isyEM.QHandler,prerestart=self.isyEM.PreRestartQHThread,poststart=self.isyEM.PostStartQHThread,postrestart=self.isyEM.PostStartQHThread)
		logsupport.Logs.Log("Finished creating Structure for ISY hub: {}".format(name))
	# noinspection PyUnusedLocal
	def _ISYVarChanged(self, storeitem, old, new, param, chgsource):
		if not chgsource:  # only send to ISY if change didn't originate there
			if new is not None:
				val = int(new)  # ISY V4 only allows integer variable values - may change in V5
				varid = storeitem.Attribute
				self.try_ISY_comm('vars/set/' + str(varid[0]) + '/' + str(varid[1]) + '/' + str(val))
			else:
				logsupport.Logs.Log("Attempt to set ISY var to None: ", storeitem.name)

	def CheckStates(self):
		# sanity check all states in Hub against local cache
		logsupport.Logs.Log("Running state check for ISY hub: ",self.name)
		for nm, N in self._NodesByFullName.items():
			if isinstance(N, Node): self._check_real_time_node_status(N)

	def try_ISY_comm(self, urlcmd, timeout=5, closeonfail=True):
		# todo suppress error messages unless multiple failures but keep track of number for patterning consistent recoverable failures
		# or perhaps informative message when recovery happens (e.g, recovered on try "n"
		error = ['Errors']
		reqtm = time.time()
		for i in range(10):
			try:
				try:
					self.HBDirect.Entry('(' + str(i) + ') Cmd: ' + self.ISYprefix + urlcmd)
					r = self.ISYrequestsession.get(self.ISYprefix + urlcmd, verify=False, timeout=timeout)
				except requests.exceptions.ConnectTimeout as e:
					self.HBDirect.Entry('(' + str(i) + ') ConnectionTimeout: ' + repr(e))
					if error[-1] != 'ConnTO': error.append('ConnTO')
					logsupport.Logs.Log(self.name + " Comm Timeout: " + ' Cmd: ' + '*' + urlcmd + '*',
										severity=ConsoleDetailHigh,
										tb=False)
					logsupport.Logs.Log(sys.exc_info()[1], severity=ConsoleDetailHigh, tb=False)
					logsupport.Logs.Log("Exc: ", e, severity=ConsoleDetailHigh, tb=False)
					raise CommsError
				except requests.exceptions.ConnectionError as e:
					# noinspection PyBroadException
					self.HBDirect.Entry('(' + str(i) + ') ConnectionError: ' + repr(e))
					if error[-1] != 'ConnErr': error.append('ConnErr')
					logsupport.Logs.Log(self.name + " Comm ConnErr: " + ' Cmd: ' + urlcmd,
										severity=ConsoleDetailHigh,
										tb=False)
					logsupport.Logs.Log(sys.exc_info()[1], severity=ConsoleDetailHigh, tb=False)
					time.sleep(30)  # network may be resetting
					raise CommsError

				except requests.exceptions.ReadTimeout as e:
					self.HBDirect.Entry('(' + str(i) + ') ReadTimeout: ' + repr(e))
					if error[-1] != 'ReadTO': error.append('ReadTO')
					raise CommsError
				except Exception as e:
					self.HBDirect.Entry('(' + str(i) + ') UnknownError: ' + repr(e))
					if error[-1] != 'CommUnknErr': error.append('CommUnknErr')
					logsupport.Logs.Log(self.name + " Comm UnknownErr: " + ' Cmd: ' + urlcmd, severity=ConsoleError,
										tb=False)
					logsupport.Logs.Log("  Exception: ", repr(e))
					logsupport.Logs.Log(sys.exc_info()[1], tb=True)
					raise CommsError
				if r.status_code == 404:  # not found
					return 'notfound'
				if r.status_code != 200:
					self.HBDirect.Entry('(' + str(i) + ') Not Success: ' + repr(r.status_code))
					if error[-1] != 'FailReq': error.append('FailReq')
					logsupport.Logs.Log('Hub (' + self.name +') Bad status:' + str(r.status_code) + ' on Cmd: ' + urlcmd,
										severity=ConsoleError)
					logsupport.Logs.Log(r.text)
					raise CommsError
				else:
					if i != 0:
						logsupport.Logs.Log(self.name + " required ", str(i + 1) + " tries over " +
											str(time.time() - reqtm) + " seconds " + str(error))
					self.HBDirect.Entry(r.text)
					return r.text
			except CommsError:
				if self.Busy != 0:
					logsupport.Logs.Log("{} comm error while busy for {.2f} seconds".format(self.name, self.Busy))
				time.sleep(5)
				logsupport.Logs.Log(self.name + " Attempting retry " + str(i + 1), severity=ConsoleDetailHigh, tb=False)
		if closeonfail:
			logsupport.Logs.Log(
				self.name + " Fatal Communications Failure - Hub Unavailable for " + str(time.time() - reqtm) +
				" seconds " + str(error), severity=ConsoleError, tb=False)
			self._HubOnline = False
			self.isyEM.EndWSServer()
			return ""
		else:
			logsupport.Logs.Log(
				self.name + " Non-fatal Communications Failure - Hub Unavailable for " + str(time.time() - reqtm) +
				" seconds " + str(error), severity=ConsoleWarning)
			return ""

	def _check_real_time_node_status(self, TargNode):
		text = self.try_ISY_comm('status/' + TargNode.address)
		if text != "":
			props = xmltodict.parse(text)['properties']['property']
			if isinstance(props, dict):
				props = [props]
			devstate = 0
			for item in props:
				if item['@id'] == "ST":
					devstate = isycodes._NormalizeState(item['@value'])
					break
		else:
			devstate = -99999

		if TargNode.devState != int(devstate):
			logsupport.Logs.Log("ISY state anomoly in hub: ", self.name, ' Node: ', TargNode.fullname, ' (', TargNode.address, ') Cached: ',
								TargNode.devState, ' Actual: ', devstate, severity=ConsoleWarning, hb=True)
			TargNode.devState = devstate # fix the state

	@staticmethod
	def _LinkChildrenParents(nodelist, listbyname, looklist1, looklist2):

		for node in nodelist.values():
			listbyname[node.name] = node
			if node.parent in looklist1:
				node.parent = looklist1[node.parent]  # replace address with actual object
			elif node.parent in looklist2:
				node.parent = looklist2[node.parent]
			else:
				node.parent = None
				logsupport.Logs.Log("Missing parent: " + node.name, severity=ConsoleError)
			if node.parent != node:  # avoid root
				node.parent.children.append(node)

	def GetNode(self, name, proxy=''):
		# return (Control Obj, Monitor Obj)
		ISYObj = self._GetSceneByName(name)
		if ISYObj is not None:
			MObj = None
			if proxy != '':
				# explicit proxy assigned
				if proxy in self.NodesByAddr:
					# address given
					MObj = self.NodesByAddr[proxy]
					debug.debugPrint('Screen', "Scene ", name, " explicit address proxying with ", MObj.name, '(', proxy, ')')
				elif self._NodeExists(proxy):
					MObj = self._GetNodeByName(proxy)
					debug.debugPrint('Screen', "Scene ", name, " explicit name proxying with ",
							   MObj.name, '(', MObj.address, ')')
				else:
					logsupport.Logs.Log('Bad explicit scene proxy:' + proxy + ' for '+ name, severity=ConsoleWarning)
					return None, None
			else:
				for i in ISYObj.members:
					device = i[1]
					if device.enabled:
						MObj = device
						break
					else:
						logsupport.Logs.Log('Skipping disabled/nonstatus device: ' + device.name, severity=ConsoleWarning)
				if MObj is None:
					logsupport.Logs.Log("No proxy for scene: " + name, severity=ConsoleError)
				debug.debugPrint('Screen', "Scene ", name, " default proxying with ", MObj.name)
			return ISYObj, MObj
		elif self._NodeExists(name):
			ISYObj = self._GetNodeByName(name)
			return ISYObj, ISYObj
		else:
			return None, None

	def GetProgram(self, name):
		try:
			return self._ProgramsByName[name]
		except KeyError:
			logsupport.Logs.Log("Attempt to access unknown program: " + name + " in ISY Hub " + self.name, severity = ConsoleWarning)
			return None

	def GetCurrentStatus(self,MonitorNode):
		if not self._HubOnline: return -1
		if MonitorNode is not None:
			return MonitorNode.devState
		else:
			return None

	def SetAlertWatch(self, node, alert):
		if node.address in self.isyEM.AlertNodes:
			self.isyEM.AlertNodes[node.address].append(alert)
		else:
			self.isyEM.AlertNodes[node.address] = [alert]

	def StatesDump(self):
		for n, nd in self._NodesByFullName.items():
			if hasattr(nd,'devState'):
				print('Node(', type(nd), '): ', n, ' -> ', nd.devState, type(nd.devState))
			else:
				print('Node(', type(nd), '): ', n, ' has no devState')

	def _SetFullNames(self, startpoint, parentname):
		startpoint.fullname = parentname + startpoint.name
		self._NodesByFullName[startpoint.fullname] = startpoint
		if isinstance(startpoint, TreeItem):
			for c in startpoint.children:
				self._SetFullNames(c, startpoint.fullname + '/')

	def _GetNodeByName(self, name):
		if name[0] == '/':
			# use fully qualified name
			return self._NodesByFullName[name]
		else:
			# use short name
			return self._NodesByName[name]

	def _NodeExists(self, name):
		if name[0] == '/':
			return name in self._NodesByFullName
		else:
			return name in self._NodesByName

	def _GetSceneByName(self,name):
		if name[0] != '/':
			if name in self._ScenesByName:
				return self._ScenesByName[name]
			else:
				return None
		else:
			for n, s in self._ScenesByName.items():
				if name == s.fullname:
					return s
			return None

	def PrintTree(self, startpoint, indent, msg):
		if msg is not None:
			debug.debugPrint('ISYdbg', 'Graph for ', msg)
		if isinstance(startpoint, Scene):
			debug.debugPrint('ISYdbg', indent + startpoint.__repr__())
			for m in startpoint.members:
				if m[0] == 16:
					sR = 'R'
				elif m[0] == 32:
					sR = 'C'
				else:
					sR = 'X'
				debug.debugPrint('ISYdbg', indent + "-" + sR + "--" + (m[1].__repr__()))
		elif isinstance(startpoint, TreeItem):
			debug.debugPrint('ISYdbg', indent + startpoint.__repr__())
			for c in startpoint.children:
				self.PrintTree(c, indent + "....", None)
		else:
			debug.debugPrint('ISYdbg', "Funny thing in tree ", startpoint.__repr__)
