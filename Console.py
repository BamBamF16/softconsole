"""
Copyright 2016 Kevin Kahn

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""

import config
from config import debugprint
from configobj import ConfigObj
import TouchArea
import ConfigObjects
import DisplayScreen
import pygame
import RPi.GPIO as GPIO
import ISYSetup
import multiprocessing
from  multiprocessing import Process, Queue
import WatchDaemon
import sys, signal, time, os
import LogSupport
from LogSupport import Logs
import webcolors
wc = webcolors.name_to_rgb

"""
The next import is functional in that it is what causes the screen types to be registered with the Console
"""
import ClockScreen, KeyScreen, ThermostatScreen, WeatherScreen, MaintScreen

def signal_handler(signal, frame):
    print "Signal: {}".format(signal)
    print "pid: ", os.getpid()
    time.sleep(1)
    pygame.quit()
    print time.time(),"Console Exiting"
    sys.exit(0)
    
def daemon_died(signal, frame):
    print "CSignal: {}".format(signal)
    if config.DaemonProcess == None:
        return
    if config.DaemonProcess.is_alive():
        print "Child ok"
    else:
        print time.time(),"Daemon died!"
        pygame.quit()
        sys.exit()

"""
Actual Code to Drive Console
"""
config.starttime = time.time()


os.environ['SDL_FBDEV'] = '/dev/fb1'
os.environ['SDL_MOUSEDEV'] = '/dev/input/touchscreen'
os.environ['SDL_MOUSEDRV'] = 'TSLIB'
os.environ['SDL_VIDEODRIVER'] = 'fbcon'

pygame.display.init()
pygame.font.init()
config.screenwidth, config.screenheight = (pygame.display.Info().current_w, pygame.display.Info().current_h)
config.screen = pygame.display.set_mode((config.screenwidth,config.screenheight), pygame.FULLSCREEN)
config.screen.fill((0, 0, 0)) # clear screen  
pygame.display.update()
pygame.mouse.set_visible(False)

        
config.Logs = LogSupport.Logs(config.screen)
Logs = config.Logs

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGCHLD, daemon_died)

config.screen.fill(wc('royalblue'))
Logs.Log(u"Soft ISY Console")
Logs.Log(u"  \u00A9 Kevin Kahn 2016")
Logs.Log("Software under Apache 2.0 License")
Logs.Log("Start time: "+time.strftime('%c'))
Logs.Log("Console Starting  pid:" + str(os.getpid()))

config.DS = DisplayScreen.DisplayScreen()



if len(sys.argv) == 2:
    config.ParsedConfigFile = ConfigObj(infile=sys.argv[1])
else:
    config.ParsedConfigFile = ConfigObj(infile="/home/pi/Console/config.txt")

# Global settings from config file
config.ISYaddr        = str(config.ParsedConfigFile.get("ISYaddr",""))
config.ISYuser        = str(config.ParsedConfigFile.get("ISYuser",""))
config.ISYpassword    = str(config.ParsedConfigFile.get("ISYpassword",""))
config.HomeScreenName = str(config.ParsedConfigFile.get("HomeScreenName",""))
config.HomeScreenTO   = int(config.ParsedConfigFile.get("HomeScreenTO",config.HomeScreenTO))
config.DimLevel       = int(config.ParsedConfigFile.get("DimLevel",config.DimLevel))
config.BrightLevel    = int(config.ParsedConfigFile.get("BrightLevel",config.BrightLevel))
config.DimTO          = int(config.ParsedConfigFile.get("DimTO",config.DimTO))
config.CmdKeyCol      = str(config.ParsedConfigFile.get("CmKeyColor",config.CmdKeyCol))
config.CmdCharCol     = str(config.ParsedConfigFile.get("CmdCharCol",config.CmdCharCol))
config.DimHomeScreenCoverName = str(config.ParsedConfigFile.get("DimHomeScreenCoverName",""))


GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(18, GPIO.OUT)
config.backlight = GPIO.PWM(18,1024)
config.backlight.start(100)

config.ConnISY = ISYSetup.ISYsetup()
nodemgr = config.ConnISY.myisy.nodes
programs = config.ConnISY.myisy.programs
if config.ConnISY.myisy.connected:
    Logs.Log("Connected to ISY: "+config.ISYaddr)
else:
    Logs.Log("Failed to connect to ISY",Logger.Error)

config.ConnISY.WalkFolder(nodemgr)
Logs.Log("Enumerated ISY Devices/Scenes")
config.ConnISY.EnumeratePrograms(programs)
Logs.Log("Enumerated ISY Programs")

pygame.fastevent.init()
CurrentScreenInfo = ConfigObjects.MyScreens()

"""
Set up the Maintenance Screen
"""
Logs.Log("Built Maintenance Screen")
config.HomeScreen2 = MaintScreen.MaintScreenDesc()  # temp use of HS2

"""
Set up the watcher daemon and its communitcations
"""
config.toDaemon = Queue()
config.fromDaemon = Queue()
p = Process(target=WatchDaemon.Watcher, name="Watcher")

p.daemon = True

p.start()
config.DaemonProcess = p
debugprint(config.dbgMain, "Spawned watcher as: ", p.pid)
Logs.Log("Watcher pid: " + str(p.pid))

TouchArea.InitButtonFonts()

Logs.livelog = False
time.sleep(2)

"""
Loop here using screen type to choose renderer and names to fill in cmdtxt - return value should be cmdbutindex
"""

config.backlight.ChangeDutyCycle(config.BrightLevel)
config.currentscreen = config.HomeScreen
prevscreen = None
while 1:
    nextscreen = config.currentscreen.HandleScreen(prevscreen <> config.currentscreen)
    if isinstance(nextscreen, int):
        if nextscreen < 6:
            nextscreen = config.HomeScreen2
        else:
            nextscreen = config.MaintScreen
            break
    prevscreen = config.currentscreen
    config.currentscreen = nextscreen
    
        
pygame.quit()
