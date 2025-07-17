# LiquidctlGUI
LiquidctlGUI is attempt of creating simple interface for liquidctl (https://github.com/liquidctl/liquidctl) using AI 
because i am not coder and your cat might be set on fire if you run this code so no any promises😉



You have to have liquidctl installed search it trough your package manager or install it via terminal using pip


sudo apt update  /  sudo yum update  /  sudo dnfupdate


sudo apt or yum or dnf install python3 python3-pip


pip3 install liquidctl


pip3 install pyqt6

<img width="804" height="526" alt="1" src="https://github.com/user-attachments/assets/813ab3e3-97fa-4a2e-8c29-0fb380bff942" />
<img width="799" height="516" alt="Screenshot_20250717_232045" src="https://github.com/user-attachments/assets/cc34e465-027c-4783-a83d-39fd44eb69e6" />


So what works and what not(atleast on my system)
----------------------------------------------------------------------------------

-list devices  --it lists devices installed in your pc supported by liquidctl

-get status     --fan speeds,pump speeds,number of fans and water temp

-setting fan speed   --sets all fan speed to a given slider position

-setting pump speed  --sets pump speed to a given slider position

-profiles work partialy i need to change to save them into some config in home folder



What it doesnt work or it is bugged
---------------------------------------------------------------------------------

-rgb control is curently unsupported on my system using crosair H170 water cooling it has broken status on liquidctl 
(rgb lights sometimes blink when setting fan and pump speed,why idk)


What i would like to add
--------------------------------------
-program icon

-actuall working rgb control 

-settings to save or load saved user settings




