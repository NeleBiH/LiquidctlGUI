# LiquidctlGUI
LiquidctlGUI is attempt of creating simple interface for liquidctl (https://github.com/liquidctl/liquidctl) using AI 
because i am not coder and your cat might be set on fire if you run this code so no any promises😉

You have to have liquidctl installed search it trough your package manager or install it via terminal using pip
udo apt update  /  sudo yum update  /  sudo dnfupdate
sudo apt or yum or dnf install python3 python3-pip
pip3 install liquidctl


![Screenshot_20240623_005616](https://github.com/NeleBiH/LiquidctlGUI/assets/86635498/f120e303-b2cd-4337-9431-1b435be0bce1)

![Screenshot_20240623_033421](https://github.com/NeleBiH/LiquidctlGUI/assets/86635498/a176cbe7-764d-4551-9815-16311d475166)

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



