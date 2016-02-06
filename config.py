import LogSupport
import pygame

screentypes = {}

starttime = 0

WAITNORMALBUTTON = 1
WAITEXIT = 2
WAITISYCHANGE = 4
WAITEXTRACONTROLBUTTON = 5
WAITDBLTAP = 7
WAITQUADTAP = 8
#WAITMAINTTAP = 9
WAITNORMALBUTTONFAST = 10

""" Daemon related stuff"""
toDaemon = None
fromDaemon = None
watchlist =[]
watchstarttime = 0
DaemonProcess = None
seq = 0
streamid = ""

# Debug flags
isytreewalkdbgprt = False
dbgscreenbuild = False
dbgMain = False
dbgdaemon = False

def debugprint(flag,*args):
    if flag:
        for arg in args:
            print arg,
        print

Logs = None

ConnISY = None

screen = None
backlight = None
DS = None

ParsedConfigFile = None
screenwidth = 320
screenheight = 480
dispratio = 1

horizborder = 20
topborder = 20
botborder = 80
cmdvertspace = 10 # this is the space around the top/bot of  cmd button within the bot border

# Global Defaults
ISYaddr = ""
ISYuser = ""
ISYpassword = ""

currentscreen = None

HomeScreenName = ""
HomeScreen = None
HomeScreen2 = None
MaintScreen = None
DimHomeScreenCoverName = ""
DimHomeScreenCover = None
DimLevel = 10
BrightLevel = 100
HomeScreenTO = 60 
DimTO = 20
CmdKeyCol = "red"
CmdCharCol = "white"
multitaptime = 300

# General Screen Defaults
BColor = "maroon"

# Key Screen Defaults


# Key Defaults
Kcolor = "aqua"
KOnColor = "white"
KOffColor = "black"
Ktype = "ONOFF" # ONOFF ONBLINKRUNTHEN
Krunthen = ""

# Clock Screen Defaults
CharColor = "white"
CharSize = 35


