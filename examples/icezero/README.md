
Simple example project for the IceZero Board
--------------------------------------------

This example design outputs the pin description for each IO pin on that IO pin
using 9600 baud TTL-level RS232 signaling (+3.3V, non-inverted).

This example comes with its own IceZero programming tool (icezprog.c).

Original programming script by Kevin M. Hubbard can be found here:
https://github.com/blackmesalabs/ice_zero_prog


IceZero Getting Started Guide
-----------------------------

**Step 1:** Get the raspbian image with pre-installed FOSS iCE40 tools:  
http://files.clifford.at/2017-03-02-raspbian-jessie-icotools.zip

And unzip the file and write the image on a (min 16 GB) SD card. See this link for instructions:  
https://www.raspberrypi.org/documentation/installation/installing-images/README.md


-- or --

Install the icestorm toolchain via:

    sudo apt-get install fpga-icestorm arachne-pnr

**Step 2:** Connect your IceZero with your Raspberry Pi or Raspberry Pi Zero and boot
the Raspberry Pi from the SD card.

**Step 2:** Copy the files in this directory onto the Raspberry Pi and build the
IceZero programming tool:

    make icezprog

and optionally

    sudo make install_icezprog

**Step 5:** Build the example design and program it into the IceZero board:

    make prog

