
all: icezero.bin

prog: icezero.bin icezprog
	./icezprog icezero.bin

reset: icezprog
	./icezprog .

icezprog: icezprog.c
	gcc -o icezprog -Wall icezprog.c -lwiringPi -lrt -lstdc++

install_icezprog: icezprog
	cp icezprog /usr/local/bin/icezprog

icezero.blif: icezero.v memdata.dat defines.vh
	yosys -p 'synth_ice40 -top top -blif icezero.blif' icezero.v

icezero.asc: icezero.blif icezero.pcf
	arachne-pnr -d 8k -P tq144:4k -p icezero.pcf -o icezero.asc icezero.blif

icezero.bin: icezero.asc
	icetime -d hx8k -c 25 icezero.asc
	icepack icezero.asc icezero.bin

memdata.dat: generate.py
	python3 generate.py

defines.vh: memdata.dat

testbench: testbench.v icezero.v
	iverilog -o testbench testbench.v icezero.v ../../icosoc/common/sim_sram.v $(shell yosys-config --datdir/ice40/cells_sim.v)

testbench.vcd: testbench
	./testbench

clean:
	rm -f testbench testbench.vcd
	rm -f icezero.blif icezero.asc icezero.bin
	rm -f memdata.dat defines.vh

.PHONY: all prog reset clean

