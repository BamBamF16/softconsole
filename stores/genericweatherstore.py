import time
from collections import OrderedDict
from random import random

import pygame

import threading

import config
import logsupport
from logsupport import ConsoleWarning, ConsoleDetail

from stores import valuestore

'''
At the generic level defining the available fields seems reasonable; issue with the specific sources holding their mappings 
should they do it entirely inside their instance or use the mapinfo idea of the store; leaning toward the former since
no real reason to store the map in the store and it is only used to populate the store on a refresh

icon/icon cache - should different sources have different caches?  Different icons if multiple sources happen to get used?
'''

CondFields = (
	('Time', str), ('Location', str), ('Temp', float), ('Sky', str), ('Feels', float), ('WindDir', str),
	('WindMPH', float), ('WindGust', int), ('Sunrise', str), ('Sunset', str), ('Moonrise', str),
	('Moonset', str), ('Humidity', str), ('Icon', pygame.Surface), ('TimeEpoch', int), ('Age', None))
FcstFields = (('Day', str), ('High', float), ('Low', float), ('Sky', str), ('WindSpd', float), ('WindDir', str),
			  ('Icon', pygame.Surface))
CommonFields = (('FcstDays', int), ('FcstEpoch', int), ('FcstDate', str))


class WeatherItem(valuestore.StoreItem):
	def __init__(self, name, Store, vt=None):
		# self.MapInfo = mapinfo
		super(WeatherItem, self).__init__(name, None, store=Store, vt=vt)


class WeatherVals(valuestore.ValueStore):

	def __init__(self, location, weathersource, refresh):
		self.failedfetchcount = 0
		self.failedfetchtime = 0
		self.refreshinterval = 60 * refresh
		if config.mqttavailable:  # randomize refresh intervals
			self.refreshinterval += int((random() * .05) * self.refreshinterval)
		super().__init__(location)
		self.ws = weathersource
		self.fetchcount = 0
		self.vars = {'Cond': OrderedDict(), 'Fcst': OrderedDict(), 'FcstDays': 0, 'FcstEpoch': 0, 'FcstDate': ''}
		self.location = location
		self.name = location
		self.ws.ConnectStore(self)
		self.DoingFetch = None  # thread that is handling a fetch or none
		self.ValidWeather = False  # status result
		self.StatusDetail = None
		self.ValidWeatherTime = 0
		self.CurFetchGood = False
		self.startedfetch = 0
		self.Status = ('Weather not available', '(Initial fetch)')

		for fld, fldtype in CondFields:
			nm = ('Cond', fld)
			self.vars['Cond'][fld] = WeatherItem(nm, self, vt=fldtype)
		for fld, fldtype in FcstFields:
			nm = ('Fcst', fld)
			self.vars['Fcst'][fld] = WeatherItem(nm, self, vt=fldtype)
			self.vars['Fcst'][fld].Value = valuestore.StoreList(self.vars['Fcst'][fld])
		for fld, fldtype in CommonFields:
			self.vars[fld] = WeatherItem(fld, self, vt=fldtype)
		for n, fcst in self.vars['Fcst'].items():
			fcst.Value = valuestore.StoreList(fcst)

	def FetchComplete(self):
		self.DoingFetch = None
		if self.CurFetchGood:
			self.failedfetchcount = 0
			self.fetchcount += 1
			self.Status = ("Weather available",)
		else:
			self.failedfetchcount += 1
			if time.time() > self.ValidWeatherTime + 3 * self.refreshinterval:  # use old weather for up to 3 intervals
				# really have stale data
				self.ValidWeather = False
				if self.StatusDetail is None:
					self.Status = ("Weather not available", "(failed fetch)")
					logsupport.Logs.Log(
						'{} weather fetch failures for: {} No weather for {} seconds'.format(self.failedfetchcount,
																							 self.name,
																							 time.time() - self.ValidWeatherTime),
						severity=ConsoleWarning)
				else:
					self.Status = ("Weather not available", self.StatusDetail)
				self.failedfetchtime = time.time()
			else:
				logsupport.Logs.Log(
					'Failed fetch for {} number {} using old weather'.format(self.name, self.failedfetchcount))

	def BlockRefresh(self):  # return True if refresh happened

		# if self.fetchtime + self.refreshinterval > time.time():
		now = time.time()
		if (now - self.ValidWeatherTime < self.refreshinterval) or (now - self.failedfetchtime < 120):
			# have recent data or a recent failure
			return False

		logsupport.Logs.Log(
			'Try weather refresh: {} age: {} {} {} {} {}'.format(self.name, (now - self.ValidWeatherTime),
																 self.ValidWeatherTime, self.refreshinterval,
																 self.failedfetchtime, now),
			severity=ConsoleDetail)

		if self.DoingFetch is None:
			logsupport.Logs.Log(
				'Do weather refresh: {} age: {} {} {} {} {}'.format(self.name, (now - self.ValidWeatherTime),
																	self.ValidWeatherTime, self.refreshinterval,
																	self.failedfetchtime, now),
				severity=ConsoleDetail)
			self.CurFetchGood = False
			self.DoingFetch = threading.Thread(target=self.ws.FetchWeather, name='WFetch-{}'.format(self.name),
											   daemon=True)
			self.DoingFetch.start()
			self.Status = ("Fetching",)
			self.startedfetch = time.time()
		# no thread doing a fetch at this point - start one

		elif self.DoingFetch.is_alive():
			# fetch in progress
			logsupport.Logs.Log(
				'Weather refresh already in progress: {} age: {} {} {} {} {}'.format(self.name,
																					 (now - self.ValidWeatherTime),
																					 self.ValidWeatherTime,
																					 self.refreshinterval,
																					 self.failedfetchtime, now),
				severity=ConsoleDetail)
			if self.startedfetch + self.refreshinterval < time.time():
				# fetch ongoing too long - don't use stale data any longer
				self.Status = ('Weather not available', '(trying to fetch)')
				logsupport.Logs.Log('Weather fetch taking long time for: {}'.format(self.name),
									severity=ConsoleWarning)
		else:
			# fetch completed todo not needed once Weatherbit is only provider since moved to FetchComplete in provider - this then should get replaced by anomoly error
			logsupport.Logs.Log('Weather refresh completed: {} age: {} {} {} {} {}'.format(self.name,
																						   (
																								   now - self.ValidWeatherTime),
																						   self.ValidWeatherTime,
																						   self.refreshinterval,
																						   self.failedfetchtime, now),
								severity=ConsoleDetail)

			self.FetchComplete()

		return True


