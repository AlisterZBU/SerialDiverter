If you run Amateur Radio logging software in CW mode, and have built a R-Pi Pico Winkeyer, 
then you will know that the default baudrates of Winkeyer and Pico reset command are both 1,200Bd.

The diverter solves the problem by taking 1,200Bd in and sending at 9,600Bd to the Pico, and vice-versa.

You may like to have a useful batch file to start the diverter then SD.EXE.
Other Amateur Radio logging programs would probably work if they are 'Winkeyer'-compatible.

The diverter and batch file were build by ChatGPT.
This is uploaded on 30th September 2026.

#!/bin/bash

# Start the serial diverter
python3 "$HOME/serial_diverter.py" &>/dev/null &
DIVERTER_PID=$!

# Make sure the diverter is stopped when this script exits
trap 'kill "$DIVERTER_PID" 2>/dev/null' EXIT INT TERM

# Run SD
cd "$HOME/.wine/drive_c/SD"
wineconsole SD.EXE

# SD has exited; trap will terminate the diverter
