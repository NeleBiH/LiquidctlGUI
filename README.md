# LiquidctlGUI
LiquidctlGUI is attempt of creating simple interface for liquidctl (https://github.com/liquidctl/liquidctl) using AI 
because i am not coder and your cat might be set on fire if you run this code so no any promises😉

You have to have liquidctl installed search it trough your package manager or install it via terminal using pip
udo apt update  /  sudo yum update  /  sudo dnfupdate
sudo apt or yum or dnf install python3 python3-pip
pip3 install liquidctl
pip3 install pyqt5


![Screenshot_20240623_035825](https://github.com/NeleBiH/LiquidctlGUI/assets/86635498/ec5c0413-88c1-4d53-b81f-1c25b6d39b06)
![Liquidctl GUI](https://github.com/NeleBiH/LiquidctlGUI/assets/86635498/440cad7f-ece4-47c5-9cc8-12f6387473dc)


So what works and what not(atleast on my system)
----------------------------------------------------------------------------------
-list devices  --it it lists devices installed in your pc supported by liquidctl
-get status     --fan speeds,pump speeds,number of fans and water temp
-setting fan speed   --sets all fan speed to a given slider position
-setting pump speed  --sets pump speed to a given slider position
-error handling --it outputs state and possible errors

What it doesnt work or it is bugged
---------------------------------------------------------------------------------
-rgb control is curently unsupported on my system using crosair H170 water cooling
-rgb lights sometimes blink when setting fan and pump speed,why idk

What i would like to add
--------------------------------------
-program icon
-tray icon
-controls from try icon on right click
-saving settings
-system info on side
-actuall working rgb control 



