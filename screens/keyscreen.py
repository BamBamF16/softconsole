# noinspection PyProtectedMember
import pygame
from configobj import Section

import debug
import keyspecs
import logsupport
import screen
import screens.__screens as screens
import utilities
from logsupport import ConsoleWarning


class KeyScreenDesc(screen.BaseKeyScreenDesc):
	def __init__(self, screensection, screenname, parentscreen=None):
		screen.BaseKeyScreenDesc.__init__(self, screensection, screenname, parentscreen=parentscreen)
		debug.debugPrint('Screen', "New KeyScreenDesc ", screenname)

		# Build the Key objects
		for keyname in screensection:
			if isinstance(screensection[keyname], Section):
				self.Keys[keyname] = keyspecs.CreateKey(self, screensection[keyname], keyname)

		self.LayoutKeys()

		debug.debugPrint('Screen', "Active Subscription List for ", self.name, " will be:")
		for h, l in self.HubInterestList.items():
			for i, j in l.items():
				m1 = "  Subscribe on hub {} node: {} {}".format(h, i, j.name)
				m2 = ""
				try:
					m2 = ":{} via {}".format(j.ControlObj.name, j.DisplayObj.name)
				except:
					pass
				debug.debugPrint('Screen', m1 + m2)

		utilities.register_example("KeyScreenDesc", self)

	def __repr__(self):
		return screen.ScreenDesc.__repr__(self) + "\r\n     KeyScreenDesc:" + ":<" + str(self.Keys) + ">"

	def InitDisplay(self, nav):
		debug.debugPrint("Screen", "Keyscreen InitDisplay: ", self.name)
		for K in self.Keys.values():
			K.InitDisplay()
		super().InitDisplay(nav)
		pygame.display.update()

	def NodeEvent(self, evnt):  # tempdel , hub='', node=0, value=0, varinfo=()):
		# Watched node reported change event is ("Node", addr, value, seq)
		debug.debugPrint('Screen', evnt)

		if evnt.node is None:  # all keys for this hub
			for _, K in self.HubInterestList[evnt.hub].items():
				debug.debugPrint('Screen', 'KS Wildcard ISYEvent ', K.name, evnt)
				K.UnknownState = True
				K.PaintKey()
				pygame.display.update()
		elif evnt.node != 0:
			# noinspection PyBroadException
			try:
				K = self.HubInterestList[evnt.hub][evnt.node]
			except:
				debug.debugPrint('Screen', 'Bad key to KS - race?', self.name, str(evnt.node))
				return  # treat as noop
			debug.debugPrint('Screen', 'KS ISYEvent ', K.name, evnt, str(K.State))
			if hasattr(K, 'HandleNodeEvent'):  # todo make all handle event key specifig
				print('Key specific node event {}'.format(K.name))
				K.HandleNodeEvent(evnt)
			else:
				if not isinstance(evnt.value, int):
					logsupport.Logs.Log("Node event with non integer state: " + evnt,
										severity=ConsoleWarning)
					evnt.value = int(evnt.value)
				K.State = not (evnt.value == 0)  # K is off (false) only if state is 0
				K.UnknownState = True if evnt.value == -1 else False
				K.PaintKey()
				pygame.display.update()
		else:
			# noinspection PyBroadException
			try:
				# varinfo is (keyname, varname)
				K = self.Keys[evnt.varinfo[0]]
				K.PaintKey()
				pygame.display.update()
			except:
				debug.debugPrint('Screen', "Var change reported to screen that doesn't care", self.name,
								 str(evnt.varinfo))  # todo event reporting correlation to screens could use rework
				return


screens.screentypes["Keypad"] = KeyScreenDesc
