import config
import sys
import mypprint
from configobj import ConfigObj
import valuestore, localvarsupport

from logsupport import ConsoleDebug, ConsoleError, ConsoleWarning

Flags = {}
DbgFlags = ['Main', 'DaemonCtl', 'DaemonStream', 'Screen', 'ISY', 'Dispatch', 'EventList', 'Fonts', 'DebugSpecial',
			'QDump', 'LLTouch', 'Touch', 'ISYDump', 'ISYLoad']

DbgVars = ConfigObj({"LogLevel":ConfigObj({'Value':3,'VarType':'int'})})
for f in DbgFlags:
	DbgVars[f] = ConfigObj({'Value':False,'VarType':'bool'})

dbgStore = valuestore.NewValueStore(localvarsupport.LocalVars('Debug',DbgVars))

DebugFlagKeys = {}
flagspercol = 3  # number of flags per maint screen
flagsperrow = 2

def LogDebugFlags():
	for flg in DbgFlags:
		fval = dbgStore.GetVal(flg)
		if fval:
			config.Logs.Log('Debug flag ', flg, '=', fval, severity=ConsoleWarning)
			dbgStore.SetVal('LogLevel', 0) # if a debug flag is set force Logging unless explicitly overridden

def debugPrint(flag, *args):
	global Flags, DbgFlags
	if flag in DbgFlags:
		if Flags[flag]:
			try:
				print >> sys.stderr, flag, '-> ',
				for arg in args:
					print >> sys.stderr, arg,
				print >> sys.stderr
				if config.Logs is not None:
					config.Logs.Log(flag, '-> ', *args, severity=ConsoleDebug, diskonly=True)
			except:
				config.Logs.Log("Internal debug print error: ", flag, ' ', repr(args), severity=ConsoleError)
	else:
		print >> sys.stderr, "DEBUG FLAG NAME ERROR", flag


def InitFlags():
	global DbgFlags
	dbg = {}
	for flg in DbgFlags:
		try:
			dbg[flg] = config.ParsedConfigFile.get(flg, False)
		except:
			dbg[flg] = False
	return dbg

def ISYDump(fn, item, pretty = True,new=False):
	fm = 'w' if new else 'a'
	with open('/home/pi/Console/'+fn,mode=fm) as f:
		if pretty:
			if not new:
				f.write('\n--------------------------------------------------------\n')
			mypprint.pprint(item,stream=f,indent=3,width=50)
		else:
			if not new:
				f.write('\n')
			f.write(item.encode('UTF-8'))
