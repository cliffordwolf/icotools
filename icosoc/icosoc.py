#!/usr/bin/env python3

import sys, os, glob, importlib, re
from collections import defaultdict
from argparse import ArgumentParser

cmd = ArgumentParser()
cmd.add_argument("-c", "--no-clean-target",
        help="Don't generate clean:: target, generate CLEAN variable",
        action="store_true")
cmd.add_argument("-f", "--custom-firmware",
        help="Don't generate rules for firmware.elf",
        action="store_true")
opt = cmd.parse_args()

basedir = os.path.dirname(sys.argv[0])
clock_freq_hz = 20000000

icosoc_mk = defaultdict(list)
icosoc_ys = defaultdict(list)
icosoc_pcf = defaultdict(list)
icosoc_v = defaultdict(list)
testbench = defaultdict(list)

icosoc_c = list()
icosoc_h = list()

mods = dict()
used_plocs = set()
used_modtypes = set()
iowires = set()
modvlog = set()

enable_compressed_isa = False
enable_muldiv_isa = False
enable_flashmem = False
enable_flashpmem = False
enable_noflashboot = False
enable_fastflashboot = False

debug_depth = 256
debug_trigat = 0
debug_mode = "FIRST_TRIGGER"

debug_enable = "1"
debug_trigger = "1"
debug_signals = dict()
debug_ports = dict()
debug_code = list()
debug_code_append = False

board = ""
used_board = False
pmod_locs = [ ]

def setboard(boardname):
    global pmod_locs
    global board

    board = boardname

    if boardname == "icoboard":
        pmod_locs = [
            "D8 B9 B10 B11 B8 A9 A10 A11".split(),
            "A5 A2 C3 B4 B7 B6 B3 B5".split(),
            "L9 G5 L7 N6 N9 P9 M8 N7".split(),
            "T15 T14 T11 R10 R14 T13 T10 T9".split(),
        ]

    else:
        assert False

def make_pins(pname):
    global used_board
    used_board = True

    ploc = None

    m = re.match(r"^pmod(\d+)_(\d+)$", pname)
    if m:
        pmod_num = int(m.group(1))
        pmod_idx = int(m.group(2))
        assert 1 <= pmod_num <= len(pmod_locs)
        assert (1 <= pmod_idx <= 4) or (7 <= pmod_idx <= 10)
        if pmod_idx <= 4:
            ploc = pmod_locs[pmod_num-1][pmod_idx-1]
        else:
            ploc = pmod_locs[pmod_num-1][pmod_idx-3]

    if re.match(r"^pmod\d+$", pname):
        return make_pins(pname + "_10") + make_pins(pname + "_9") + make_pins(pname + "_8") + make_pins(pname + "_7") + \
               make_pins(pname + "_4") + make_pins(pname + "_3") + make_pins(pname + "_2") + make_pins(pname + "_1")

    if re.match(r"^[A-Z][0-9][0-9]?$", pname):
        ploc = pname

    assert ploc is not None
    assert ploc not in used_plocs
    used_plocs.add(ploc)

    iowires.add(pname)
    icosoc_v["12-iopins"].append("    inout %s," % pname)
    icosoc_pcf["12-iopins"].append("set_io %s %s" % (pname, ploc))
    return [ pname ]

setboard("icoboard")

def parse_cfg(f):
    global enable_compressed_isa
    global enable_muldiv_isa
    global enable_flashmem
    global enable_flashpmem
    global enable_noflashboot
    global enable_fastflashboot
    global debug_code_append

    current_mod_name = None
    cm = None

    for line_str in f:
        line = line_str.split()

        if debug_code_append:
            if line == ["debug_code_end"]:
                debug_code_append = False
            else:
                debug_code.append(line_str)
            continue

        if line == ["debug_code_begin"]:
            debug_code_append = True
            continue

        if "#" in line:
            line = line[0:line.index("#")]

        if len(line) == 0 or line[0].startswith("#"):
            continue

        if line[0] == "board":
            assert len(line) == 2
            assert current_mod_name is None
            assert not used_board
            if line[1] == "icoboard_gamma":
                setboard("icoboard")
            else:
                setboard(line[1])
            continue

        if line[0] == "compressed_isa":
            assert len(line) == 1
            assert current_mod_name is None
            enable_compressed_isa = True
            continue

        if line[0] == "muldiv_isa":
            assert len(line) == 1
            assert current_mod_name is None
            enable_muldiv_isa = True
            continue

        if line[0] == "flashmem":
            assert len(line) == 1
            assert current_mod_name is None
            enable_flashmem = True
            continue

        if line[0] == "flashpmem":
            assert len(line) == 1
            assert current_mod_name is None
            enable_flashmem = True
            enable_flashpmem = True
            continue

        if line[0] == "noflashboot":
            assert len(line) == 1
            assert current_mod_name is None
            enable_noflashboot = True
            continue

        if line[0] == "fastflashboot":
            assert len(line) == 1
            assert current_mod_name is None
            enable_fastflashboot = True
            continue

        if line[0] == "debug_net":
            assert len(line) == 2
            debug_signals[line[1]] = line[1]
            continue

        if line[0] == "debug_expr":
            assert len(line) == 4
            assert int(line[2]) == 1
            debug_signals[line[1]] = line[3]
            continue

        if line[0] == "debug_port":
            assert len(line) == 3
            make_pins(line[1])
            debug_ports[line[1]] = line[2]
            continue

        if line[0] == "mod":
            assert len(line) == 3
            current_mod_name = line[2]
            cm = {
                "name": current_mod_name,
                "type": line[1],
                "addr": None,
                "irq": None,
                "conns": defaultdict(list),
                "params": dict()
            }
            assert current_mod_name not in mods
            mods[current_mod_name] = cm

            if line[1] not in used_modtypes:
                used_modtypes.add(line[1])
                modvlog.add("%s/mod_%s/mod_%s.v" % (basedir, line[1], line[1]))
            continue

        if line[0] == "connect":
            assert len(line) >= 3
            assert current_mod_name is not None
            for pname in line[2:]:
                for pn in make_pins(pname):
                    cm["conns"][line[1]].append(pn)
            continue

        if line[0] == "param":
            assert len(line) == 3
            assert current_mod_name is not None
            cm["params"][line[1]] = line[2]
            continue

        if line[0] == "address":
            assert len(line) == 2
            assert current_mod_name is not None
            assert cm["addr"] is None
            cm["addr"] = line[1]
            continue

        if line[0] == "interrupt":
            assert len(line) == 2
            assert current_mod_name is not None
            assert cm["irq"] is None
            cm["irq"] = line[1]
            continue

        print("Cfg error: %s" % line)
        assert None

with open("icosoc.cfg", "r") as f:
    parse_cfg(f)

icosoc_h.append("""
#ifndef ICOSOC_H
#define ICOSOC_H

#include <stdint.h>
#include <stdbool.h>

#define ICOSOC_CLOCK_FREQ_HZ %d

static inline void icosoc_irq(void(*irq_handler)(uint32_t,uint32_t*)) {
    *((uint32_t*)8) = (uint32_t)irq_handler;
}

extern uint32_t icosoc_maskirq(uint32_t mask);
extern uint32_t icosoc_timer(uint32_t ticks);

static inline void icosoc_sbreak() {
    asm volatile ("sbreak" : : : "memory");
}

static inline void icosoc_leds(uint8_t value)
{
    *(volatile uint32_t *)0x20000000 = value;
}

static inline void icosoc_spiflash_begin()
{
    *(volatile uint32_t *)0x20000004 &= ~8;
}

static inline void icosoc_spiflash_end()
{
    *(volatile uint32_t *)0x20000004 |= 8;
}

static inline uint8_t icosoc_spiflash_xfer(uint8_t value)
{
    *(volatile uint32_t *)0x20000008 = value;
    return *(volatile uint32_t *)0x20000008;
}

static inline void icosoc_spiflash_read(void *buf, int offset, int length)
{
    icosoc_spiflash_begin();

    icosoc_spiflash_xfer(0x03);
    icosoc_spiflash_xfer(offset >> 16);
    icosoc_spiflash_xfer(offset >> 8);
    icosoc_spiflash_xfer(offset);

    while (length--)
        *(uint8_t*)(buf++) = icosoc_spiflash_xfer(0);

    icosoc_spiflash_end();
}
""" % clock_freq_hz);

icosoc_c.append("""
#include "icosoc.h"
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>

asm (
".global icosoc_maskirq\\n"
"icosoc_maskirq:\\n"
".word 0x0605650b\\n" // picorv32_maskirq_insn(a0, a0)
"ret\\n"
);

asm (
".global icosoc_timer\\n"
"icosoc_timer:\\n"
".word 0x0a05650b\\n" // picorv32_timer_insn(a0, a0)
"ret\\n"
);

""");

icosoc_v["20-clockgen"].append("""
    // -------------------------------
    // Clock Generator

    wire clk, clk90;
    wire pll_locked;

`ifdef TESTBENCH
    reg r_clk = 0, r_clk90 = 0;

    always @(posedge CLKIN)
        r_clk <= !r_clk;

    always @(negedge CLKIN)
        r_clk90 <= r_clk;

    assign clk = r_clk, clk90 = r_clk90;
    assign pll_locked = 1;
`else
    wire clk_100mhz, pll1_locked, pll2_locked;
    assign pll_locked = pll1_locked && pll2_locked;
    assign clk_100mhz = CLKIN;
    assign pll1_locked = 1;

    SB_PLL40_2F_CORE #(
        .FEEDBACK_PATH("PHASE_AND_DELAY"),
        .DELAY_ADJUSTMENT_MODE_FEEDBACK("FIXED"),
        .DELAY_ADJUSTMENT_MODE_RELATIVE("FIXED"),
        .PLLOUT_SELECT_PORTA("SHIFTREG_0deg"),
        .PLLOUT_SELECT_PORTB("SHIFTREG_90deg"),
        .SHIFTREG_DIV_MODE(1'b0),
        .FDA_FEEDBACK(4'b1111),
        .FDA_RELATIVE(4'b1111),
        .DIVR(4'b0100),
        .DIVF(7'b0000000),
        .DIVQ(3'b101),
        .FILTER_RANGE(3'b111)
    ) pll2 (
        .REFERENCECLK   (clk_100mhz   ),
        .PLLOUTGLOBALA  (clk          ),
        .PLLOUTGLOBALB  (clk90        ),
        .LOCK           (pll2_locked  ),
        .BYPASS         (1'b0         ),
        .RESETB         (1'b1         )
    );
`endif

    // -------------------------------
    // Reset Generator

    reg [7:0] resetn_counter = 0;
    wire resetn = &resetn_counter;

    always @(posedge clk) begin
        if (!pll_locked)
            resetn_counter <= 0;
        else if (!resetn)
            resetn_counter <= resetn_counter + 1;
    end
""")

icosoc_v["30-sramif"].append("""
    // -------------------------------
    // SRAM/HRAM Interface

    reg [1:0] sram_state;
    reg sram_wrlb, sram_wrub;
    reg [18:0] sram_addr;
    reg [15:0] sram_dout;
    wire [15:0] sram_din;

    SB_IO #(
        .PIN_TYPE(6'b 1010_01),
        .PULLUP(1'b 0)
    ) sram_io [15:0] (
        .PACKAGE_PIN({SRAM_D15, SRAM_D14, SRAM_D13, SRAM_D12, SRAM_D11, SRAM_D10, SRAM_D9, SRAM_D8,
                      SRAM_D7, SRAM_D6, SRAM_D5, SRAM_D4, SRAM_D3, SRAM_D2, SRAM_D1, SRAM_D0}),
        .OUTPUT_ENABLE(sram_wrlb || sram_wrub),
        .D_OUT_0(sram_dout),
        .D_IN_0(sram_din)
    );
""")

icosoc_v["30-sramif"].append("""
    assign {SRAM_A18, SRAM_A17, SRAM_A16, SRAM_A15, SRAM_A14, SRAM_A13, SRAM_A12, SRAM_A11, SRAM_A10, SRAM_A9, SRAM_A8,
            SRAM_A7, SRAM_A6, SRAM_A5, SRAM_A4, SRAM_A3, SRAM_A2, SRAM_A1, SRAM_A0} = sram_addr;

    assign SRAM_CE = 0;
    assign SRAM_WE = (sram_wrlb || sram_wrub) ? !clk90 : 1;
    assign SRAM_OE = (sram_wrlb || sram_wrub);
    assign SRAM_LB = (sram_wrlb || sram_wrub) ? !sram_wrlb : 0;
    assign SRAM_UB = (sram_wrlb || sram_wrub) ? !sram_wrub : 0;
    assign HRAM_CK = 0;
""")

icosoc_v["30-raspif"].append("""
    // -------------------------------
    // RasPi Interface

    wire recv_sync;

    // recv ep0: transmission test
    wire recv_ep0_valid;
    wire recv_ep0_ready;
    wire [7:0] recv_ep0_data;

    // recv ep1: unused
    wire recv_ep1_valid;
    wire recv_ep1_ready = 1;
    wire [7:0] recv_ep1_data = recv_ep0_data;

    // recv ep2: console input
    wire recv_ep2_valid;
    reg  recv_ep2_ready;
    wire [7:0] recv_ep2_data = recv_ep0_data;

    // recv ep3: unused
    wire recv_ep3_valid;
    wire recv_ep3_ready = 1;
    wire [7:0] recv_ep3_data = recv_ep0_data;

    // send ep0: transmission test
    wire send_ep0_valid;
    wire send_ep0_ready;
    wire [7:0] send_ep0_data;

    // send ep1: debugger
    wire send_ep1_valid;
    wire send_ep1_ready;
    wire [7:0] send_ep1_data;

    // send ep2: console output
    reg  send_ep2_valid;
    wire send_ep2_ready;
    reg  [7:0] send_ep2_data;

    // send ep3: unused
    wire send_ep3_valid = 0;
    wire send_ep3_ready;
    wire [7:0] send_ep3_data = 'bx;

    // trigger lines
    wire trigger_0;  // unused
    wire trigger_1;  // debugger
    wire trigger_2;  // unused
    wire trigger_3;  // unused

    icosoc_raspif #(
        .NUM_RECV_EP(4),
        .NUM_SEND_EP(4),
        .NUM_TRIGGERS(4)
    ) raspi_interface (
        .clk(clk),
        .sync(recv_sync),

        .recv_valid({
            recv_ep3_valid,
            recv_ep2_valid,
            recv_ep1_valid,
            recv_ep0_valid
        }),
        .recv_ready({
            recv_ep3_ready,
            recv_ep2_ready,
            recv_ep1_ready,
            recv_ep0_ready
        }),
        .recv_tdata(
            recv_ep0_data
        ),

        .send_valid({
            send_ep3_valid,
            send_ep2_valid,
            send_ep1_valid,
            send_ep0_valid
        }),
        .send_ready({
            send_ep3_ready,
            send_ep2_ready,
            send_ep1_ready,
            send_ep0_ready
        }),
        .send_tdata(
            (send_ep3_data & {8{send_ep3_valid && send_ep3_ready}}) |
            (send_ep2_data & {8{send_ep2_valid && send_ep2_ready}}) |
            (send_ep1_data & {8{send_ep1_valid && send_ep1_ready}}) |
            (send_ep0_data & {8{send_ep0_valid && send_ep0_ready}})
        ),

        .trigger({
            trigger_3,
            trigger_2,
            trigger_1,
            trigger_0
        }),

        .RASPI_11(RASPI_11),
        .RASPI_12(RASPI_12),
        .RASPI_15(RASPI_15),
        .RASPI_16(RASPI_16),
        .RASPI_19(RASPI_19),
        .RASPI_21(RASPI_21),
        .RASPI_26(RASPI_26),
        .RASPI_35(RASPI_35),
        .RASPI_36(RASPI_36),
        .RASPI_38(RASPI_38),
        .RASPI_40(RASPI_40)
    );

    // -------------------------------
    // Transmission test (recv ep0, send ep0)

    assign send_ep0_data = ((recv_ep0_data << 5) + recv_ep0_data) ^ 7;
    assign send_ep0_valid = recv_ep0_valid;
    assign recv_ep0_ready = send_ep0_ready;
""")

icosoc_v["40-cpu"].append("""
    // -------------------------------
    // PicoRV32 Core

    wire cpu_trap;
    wire [31:0] cpu_irq;

    wire mem_valid;
    wire mem_instr;
    wire [31:0] mem_addr;
    wire [31:0] mem_wdata;
    wire [3:0] mem_wstrb;

    reg mem_ready;
    reg [31:0] mem_rdata;

    picorv32 #(
        .COMPRESSED_ISA(<compisa>),
        .ENABLE_MUL(<muldiv>),
        .ENABLE_DIV(<muldiv>),
        .ENABLE_IRQ(1)
    ) cpu (
        .clk       (clk      ),
        .resetn    (resetn   ),
        .trap      (cpu_trap ),
        .mem_valid (mem_valid),
        .mem_instr (mem_instr),
        .mem_ready (mem_ready),
        .mem_addr  (mem_addr ),
        .mem_wdata (mem_wdata),
        .mem_wstrb (mem_wstrb),
        .mem_rdata (mem_rdata),
        .irq       (cpu_irq  )
    );
"""
.replace("<compisa>", ("1" if enable_compressed_isa else "0"))
.replace("<muldiv>", ("1" if enable_muldiv_isa else "0")))

icosoc_v["50-mods"].append("""
    // -------------------------------
    // IcoSoC Modules
""")

irq_terms = list()
txt = icosoc_v["50-mods"]
for m in mods.values():
    if m["addr"] is not None:
        txt.append("    reg [3:0] mod_%s_ctrl_wr;" % m["name"])
        txt.append("    reg mod_%s_ctrl_rd;" % m["name"])
        txt.append("    reg [15:0] mod_%s_ctrl_addr;" % m["name"])
        txt.append("    reg [31:0] mod_%s_ctrl_wdat;" % m["name"])
        txt.append("    wire [31:0] mod_%s_ctrl_rdat;" % m["name"])
        txt.append("    wire mod_%s_ctrl_done;" % m["name"])
        if m["irq"] is None:
            txt.append("")

    if m["irq"] is not None:
        irq_terms.append("mod_%s_ctrl_irq << %s" % (m["name"], m["irq"]))
        txt.append("    wire mod_%s_ctrl_irq;" % m["name"])
        txt.append("")

    txt.append("    icosoc_mod_%s #(" % m["type"])
    for para_name, para_value in m["params"].items():
        txt.append("        .%s(%s)," % (para_name, para_value))
    for cn, cd in m["conns"].items():
        if cn != cn.upper(): continue
        txt.append("        .%s_LENGTH(%d)," % (cn, len(cd)))
    txt.append("        .CLOCK_FREQ_HZ(%d)" % clock_freq_hz)
    txt.append("    ) mod_%s (" % m["name"])
    txt.append("        .clk(clk),")
    txt.append("        .resetn(resetn),")

    if m["addr"] is not None:
        for n in "wr rd addr wdat rdat done".split():
            txt.append("        .ctrl_%s(mod_%s_ctrl_%s)," % (n, m["name"], n))

    if m["irq"] is not None:
        txt.append("        .ctrl_irq(mod_%s_ctrl_irq)," % m["name"])

    for cn, cd in m["conns"].items():
        txt.append("        .%s({%s})," % (cn, ",".join(cd)))

    txt[-1] = txt[-1].rstrip(",")
    txt.append("    );")
    txt.append("")

    if m["addr"] is not None:
        if "71-bus-modinit" in icosoc_v:
            icosoc_v["71-bus-modinit"].append("");
        icosoc_v["71-bus-modinit"].append("        mod_%s_ctrl_wr <= 0;" % m["name"]);
        icosoc_v["71-bus-modinit"].append("        mod_%s_ctrl_rd <= 0;" % m["name"]);
        icosoc_v["71-bus-modinit"].append("        mod_%s_ctrl_addr <= mem_addr[15:0];" % m["name"]);
        icosoc_v["71-bus-modinit"].append("        mod_%s_ctrl_wdat <= mem_wdata;" % m["name"]);

        icosoc_v["73-bus-modwrite"].append("""
                        if (mem_addr[23:16] == %s) begin
                            mem_ready <= mod_%s_ctrl_done;
                            mod_%s_ctrl_wr <= mod_%s_ctrl_done ? 0 : mem_wstrb;
                        end
""" % (m["addr"], m["name"], m["name"], m["name"]))

        icosoc_v["75-bus-modread"].append("""
                        if (mem_addr[23:16] == %s) begin
                            mem_ready <= mod_%s_ctrl_done;
                            mod_%s_ctrl_rd <= !mod_%s_ctrl_done;
                            mem_rdata <= mod_%s_ctrl_rdat;
                        end
""" % (m["addr"], m["name"], m["name"], m["name"], m["name"]))

    if os.path.isfile("%s/mod_%s/mod_%s.py" % (basedir, m["type"], m["type"])):
        mod_loaded = importlib.import_module("mod_%s.mod_%s" % (m["type"], m["type"]))
        if hasattr(mod_loaded, "generate_c_code"):
            mod_loaded.generate_c_code(icosoc_h, icosoc_c, m)
        if hasattr(mod_loaded, "extra_vlog_files"):
            modvlog |= mod_loaded.extra_vlog_files(basedir, m)

txt.append("");
if len(irq_terms) > 0:
    txt.append("    assign cpu_irq = %s;" % " | ".join(["(" + t + ")" for t in irq_terms]))
else:
    txt.append("    assign cpu_irq = 0;");

for vlog in modvlog:
    icosoc_ys["12-readvlog"].append("read_verilog -D ICOSOC %s" % (vlog))

if len(debug_code) or len(debug_ports):
    icosoc_v["90-debug"].append("""
    // -------------------------------
    // Additional debug code
""")

    for line in debug_code:
        icosoc_v["90-debug"].append(line)

    for port, expr in debug_ports.items():
        icosoc_v["90-debug"].append("    assign %s = %s;" % (port, expr))

if len(debug_signals):
    icosoc_v["90-debug"].append("""
    // -------------------------------
    // On-chip logic analyzer (send ep1, trig1)

    wire debug_enable;
    wire debug_trigger;
    wire debug_triggered;
    wire [%d:0] debug_data;

    icosoc_debugger #(
        .WIDTH(%d),
        .DEPTH(%d),
        .TRIGAT(%d),
        .MODE("%s")
    ) debugger (
        .clk(clk),
        .resetn(resetn),

        .enable(debug_enable),
        .trigger(debug_trigger),
        .triggered(debug_triggered),
        .data(debug_data),

        .dump_en(trigger_1),
        .dump_valid(send_ep1_valid),
        .dump_ready(send_ep1_ready),
        .dump_data(send_ep1_data)
    );

    assign debug_enable = 1;
    assign debug_trigger = 1;

    assign debug_data = {""" % (len(debug_signals)-1, len(debug_signals), debug_depth, debug_trigat, debug_mode))

    idx = len(debug_signals)-1
    for label, expr in sorted(debug_signals.items(), key=(lambda item: re.sub(r"\d+", (lambda match: "%05d" % int(match.group(0))), item[0]))):
        icosoc_v["90-debug"].append("        %-20s // debug_%d -> %s" % (expr + ("," if idx != 0 else ""), idx, label))
        idx -= 1

    icosoc_v["90-debug"].append("    };")

else: # no debug signals
    icosoc_v["90-debug"].append("""
    // -------------------------------
    // On-chip logic analyzer (send ep1, trig1), disabled

    assign send_ep1_valid = 0;
    assign send_ep1_data = 'bx;
""");

if enable_flashmem:
    flashmem_condition = "((mem_addr & 32'hC000_0000) == 32'h4000_0000)"
    if enable_flashpmem:
        flashmem_condition += " || (!mem_addr[31:28] && mem_addr[27:20])"

    icosoc_v["68-flashmem"].append("""
    // -------------------------------
    // Flashmem and SPI Flash Interface

    wire [23:0] flashmem_addr = mem_addr;
    wire [31:0] flashmem_rdata;
    wire flashmem_cond = <flashmem_condition>;
    wire flashmem_valid = mem_valid && !mem_ready && flashmem_cond;
    wire flashmem_ready;

    wire flashmem_cs;
    wire flashmem_sclk;
    wire flashmem_mosi;
    wire flashmem_miso;

    reg spiflash_cs;
    reg spiflash_sclk;
    reg spiflash_mosi;
    wire spiflash_miso;

    reg [7:0] spiflash_data;
    reg [3:0] spiflash_state;

    assign SPI_FLASH_CS = flashmem_cs & spiflash_cs;
    assign SPI_FLASH_SCLK = !flashmem_cs ? flashmem_sclk : spiflash_sclk;
    assign SPI_FLASH_MOSI = !flashmem_cs ? flashmem_mosi : spiflash_mosi;
    assign flashmem_miso = SPI_FLASH_MISO, spiflash_miso = SPI_FLASH_MISO;

    icosoc_flashmem flashmem (
        .clk(clk),
        .resetn(resetn),
        .valid(flashmem_valid),
        .ready(flashmem_ready),
        .addr(flashmem_addr),
        .rdata(flashmem_rdata),
        .spi_cs(flashmem_cs),
        .spi_sclk(flashmem_sclk),
        .spi_mosi(flashmem_mosi),
        .spi_miso(flashmem_miso)
    );
""".replace("<flashmem_condition>", flashmem_condition))

else:
    icosoc_v["68-flashmem"].append("""
    // -------------------------------
    // SPI Flash Interface

    reg spiflash_cs;
    reg spiflash_sclk;
    reg spiflash_mosi;
    wire spiflash_miso;

    reg [7:0] spiflash_data;
    reg [3:0] spiflash_state;

    assign SPI_FLASH_CS = spiflash_cs;
    assign SPI_FLASH_SCLK = spiflash_sclk;
    assign SPI_FLASH_MOSI = spiflash_mosi;
    assign spiflash_miso = SPI_FLASH_MISO;

    wire flashmem_cond = 0;
""")

icosoc_v["70-bus"].append("""
    // -------------------------------
    // Memory/IO Interface

    localparam BOOT_MEM_SIZE = 1024;
    reg [31:0] memory [0:BOOT_MEM_SIZE-1];
`ifdef TESTBENCH
    initial $readmemh("firmware.hex", memory);
`else
    initial $readmemh("firmware_seed.hex", memory);
`endif

    always @(posedge clk) begin
        mem_ready <= 0;
        sram_state <= 0;
        sram_wrlb <= 0;
        sram_wrub <= 0;
        sram_addr <= 'bx;
        sram_dout <= 'bx;
""")

icosoc_v["72-bus"].append("""
        if (send_ep2_ready)
            send_ep2_valid <= 0;

        recv_ep2_ready <= 0;

        if (!resetn) begin
            LED1 <= 0;
            LED2 <= 0;
            LED3 <= 0;

            spiflash_cs   <= 1;
            spiflash_sclk <= 1;
            spiflash_mosi <= 0;

            send_ep2_valid <= 0;
            spiflash_state <= 0;
        end else
        if (mem_valid && !mem_ready) begin
            (* parallel_case *)
            case (1)
                (mem_addr >> 2) < BOOT_MEM_SIZE: begin
                    if (mem_wstrb) begin
                        if (mem_wstrb[0]) memory[mem_addr >> 2][ 7: 0] <= mem_wdata[ 7: 0];
                        if (mem_wstrb[1]) memory[mem_addr >> 2][15: 8] <= mem_wdata[15: 8];
                        if (mem_wstrb[2]) memory[mem_addr >> 2][23:16] <= mem_wdata[23:16];
                        if (mem_wstrb[3]) memory[mem_addr >> 2][31:24] <= mem_wdata[31:24];
                    end else begin
                        mem_rdata <= memory[mem_addr >> 2];
                    end
                    mem_ready <= 1;
                end
                (mem_addr & 32'hF000_0000) == 32'h0000_0000 && (mem_addr >> 2) >= BOOT_MEM_SIZE && !flashmem_cond: begin
                    if (mem_wstrb) begin
                        (* parallel_case, full_case *)
                        case (sram_state)
                            0: begin
                                sram_addr <= {mem_addr >> 2, 1'b0};
                                sram_dout <= mem_wdata[15:0];
                                sram_wrlb <= mem_wstrb[0];
                                sram_wrub <= mem_wstrb[1];
                                sram_state <= 1;
                            end
                            1: begin
                                sram_addr <= {mem_addr >> 2, 1'b1};
                                sram_dout <= mem_wdata[31:16];
                                sram_wrlb <= mem_wstrb[2];
                                sram_wrub <= mem_wstrb[3];
                                sram_state <= 0;
                                mem_ready <= 1;
                            end
                        endcase
                    end else begin
                        (* parallel_case, full_case *)
                        case (sram_state)
                            0: begin
                                sram_addr <= {mem_addr >> 2, 1'b0};
                                sram_state <= 1;
                            end
                            1: begin
                                sram_addr <= {mem_addr >> 2, 1'b1};
                                mem_rdata[15:0] <= sram_din;
                                sram_state <= 2;
                            end
                            2: begin
                                mem_rdata[31:16] <= sram_din;
                                sram_state <= 0;
                                mem_ready <= 1;
                            end
                        endcase
                    end
                end
                (mem_addr & 32'hF000_0000) == 32'h2000_0000: begin
                    mem_ready <= 1;
                    mem_rdata <= 0;
                    if (mem_wstrb) begin
                        if (mem_addr[23:16] == 0) begin
                            if (mem_addr[7:0] == 8'h 00) {LED3, LED2, LED1} <= mem_wdata;
                            if (mem_addr[7:0] == 8'h 04) {spiflash_cs, spiflash_sclk, spiflash_mosi} <= mem_wdata[3:1];
                            if (mem_addr[7:0] == 8'h 08) begin
                                if (spiflash_state == 0) begin
                                    spiflash_data <= mem_wdata;
                                    spiflash_mosi <= mem_wdata[7];
                                end else begin
                                    if (spiflash_state[0])
                                        spiflash_data <= {spiflash_data, spiflash_miso};
                                    else
                                        spiflash_mosi <= spiflash_data[7];
                                end
                                spiflash_sclk <= spiflash_state[0];
                                mem_ready <= spiflash_state == 15;
                                spiflash_state <= spiflash_state + 1;
                            end
                        end
""")

icosoc_v["74-bus"].append("""
                    end else begin
                        if (mem_addr[23:16] == 0) begin
`ifdef TESTBENCH
                            if (mem_addr[7:0] == 8'h 00) mem_rdata <= {LED3, LED2, LED1} | 32'h8000_0000;
`else
                            if (mem_addr[7:0] == 8'h 00) mem_rdata <= {LED3, LED2, LED1};
`endif
                            if (mem_addr[7:0] == 8'h 04) mem_rdata <= {spiflash_cs, spiflash_sclk, spiflash_mosi, spiflash_miso};
                            if (mem_addr[7:0] == 8'h 08) mem_rdata <= spiflash_data;
                        end
""")

icosoc_v["76-bus"].append("""
                    end
                end
                (mem_addr & 32'hF000_0000) == 32'h3000_0000: begin
                    if (mem_wstrb) begin
                        if (send_ep2_ready || !send_ep2_valid) begin
                            send_ep2_valid <= 1;
                            send_ep2_data <= mem_wdata;
                            mem_ready <= 1;
                        end
                    end else begin
                        if (recv_ep2_valid && !recv_ep2_ready) begin
                            recv_ep2_ready <= 1;
                            mem_rdata <= recv_ep2_data;
                        end else begin
                            mem_rdata <= ~0;
                        end
                        mem_ready <= 1;
                    end
                end
""")

if enable_flashmem:
    icosoc_v["77-bus"].append("""
                flashmem_cond: begin
                    mem_rdata <= flashmem_rdata;
                    mem_ready <= flashmem_ready;
                end
""")

icosoc_v["78-bus"].append("""
            endcase
        end
    end
""")

icosoc_v["10-moddecl"].append("module icosoc (")
icosoc_v["10-moddecl"].append("    input CLKIN,")
icosoc_v["10-moddecl"].append("    output reg LED1, LED2, LED3,")
icosoc_v["10-moddecl"].append("")

iowires |= set("CLKIN LED1 LED2 LED3".split())

icosoc_v["12-iopins"].append("")

icosoc_v["15-moddecl"].append("    output SPI_FLASH_CS,")
icosoc_v["15-moddecl"].append("    output SPI_FLASH_SCLK,")
icosoc_v["15-moddecl"].append("    output SPI_FLASH_MOSI,")
icosoc_v["15-moddecl"].append("    input  SPI_FLASH_MISO,")
icosoc_v["15-moddecl"].append("")

iowires.add("SPI_FLASH_CS")
iowires.add("SPI_FLASH_SCLK")
iowires.add("SPI_FLASH_MOSI")
iowires.add("SPI_FLASH_MISO")

icosoc_v["15-moddecl"].append("    // RasPi Interface: 9 Data Lines (cmds have MSB set)")
icosoc_v["15-moddecl"].append("    inout RASPI_11, RASPI_12, RASPI_15, RASPI_16, RASPI_19, RASPI_21, RASPI_26, RASPI_35, RASPI_36,")
icosoc_v["15-moddecl"].append("")
icosoc_v["15-moddecl"].append("    // RasPi Interface: Control Lines")
icosoc_v["15-moddecl"].append("    input RASPI_38, RASPI_40,")
icosoc_v["15-moddecl"].append("")

iowires |= set("RASPI_11 RASPI_12 RASPI_15 RASPI_16 RASPI_19 RASPI_21 RASPI_26 RASPI_35 RASPI_36 RASPI_38 RASPI_40".split())

icosoc_v["15-moddecl"].append("    // SRAM and HRAM Interface")
icosoc_v["15-moddecl"].append("    output SRAM_A0, SRAM_A1, SRAM_A2, SRAM_A3, SRAM_A4, SRAM_A5, SRAM_A6, SRAM_A7,")
icosoc_v["15-moddecl"].append("    output SRAM_A8, SRAM_A9, SRAM_A10, SRAM_A11, SRAM_A12, SRAM_A13, SRAM_A14, SRAM_A15,")
icosoc_v["15-moddecl"].append("    output SRAM_A16, SRAM_A17, SRAM_A18,")

icosoc_v["15-moddecl"].append("    inout SRAM_D0, SRAM_D1, SRAM_D2, SRAM_D3, SRAM_D4, SRAM_D5, SRAM_D6, SRAM_D7,")
icosoc_v["15-moddecl"].append("    inout SRAM_D8, SRAM_D9, SRAM_D10, SRAM_D11, SRAM_D12, SRAM_D13, SRAM_D14, SRAM_D15,")
icosoc_v["15-moddecl"].append("    output SRAM_CE, SRAM_WE, SRAM_OE, SRAM_LB, SRAM_UB, HRAM_CK")
icosoc_v["15-moddecl"].append(");")

iowires |= set("SRAM_A0 SRAM_A1 SRAM_A2 SRAM_A3 SRAM_A4 SRAM_A5 SRAM_A6 SRAM_A7".split())
iowires |= set("SRAM_A8 SRAM_A9 SRAM_A10 SRAM_A11 SRAM_A12 SRAM_A13 SRAM_A14 SRAM_A15".split())
iowires |= set("SRAM_D0 SRAM_D1 SRAM_D2 SRAM_D3 SRAM_D4 SRAM_D5 SRAM_D6 SRAM_D7".split())
iowires |= set("SRAM_D8 SRAM_D9 SRAM_D10 SRAM_D11 SRAM_D12 SRAM_D13 SRAM_D14 SRAM_D15".split())
iowires |= set("SRAM_CE SRAM_WE SRAM_OE SRAM_LB SRAM_UB HRAM_CK".split())

icosoc_v["95-endmod"].append("endmodule")

icosoc_pcf["10-std"].append("""
set_io CLKIN R9

set_io LED1 C8
set_io LED2 F7
set_io LED3 K9

set_io SPI_FLASH_CS   R12
set_io SPI_FLASH_SCLK R11
set_io SPI_FLASH_MOSI P12
set_io SPI_FLASH_MISO P11

set_io RASPI_11 D5
set_io RASPI_12 D6
set_io RASPI_15 C6
set_io RASPI_16 C7
set_io RASPI_19 A6
set_io RASPI_21 A7
set_io RASPI_26 D4
set_io RASPI_35 D7
set_io RASPI_36 D9
set_io RASPI_38 C9
set_io RASPI_40 C10

set_io SRAM_A0  P1
set_io SRAM_A1  N3
set_io SRAM_A2  R1
set_io SRAM_A3  P2
set_io SRAM_A4  T1
set_io SRAM_A5  T8
set_io SRAM_A6  P6
set_io SRAM_A7  M6
set_io SRAM_A8  P7
set_io SRAM_A9  M11
set_io SRAM_A10 N10
set_io SRAM_A11 P5
set_io SRAM_A12 N5
set_io SRAM_A13 P4
set_io SRAM_A14 M5
set_io SRAM_A15 J5
set_io SRAM_A16 K5
set_io SRAM_A17 N2
set_io SRAM_A18 P8

set_io SRAM_D0  T2
set_io SRAM_D1  R3
set_io SRAM_D2  T3
set_io SRAM_D3  R4
set_io SRAM_D4  R5
set_io SRAM_D5  T5
set_io SRAM_D6  R6
set_io SRAM_D7  T6
set_io SRAM_D8  N4
set_io SRAM_D9  M4
set_io SRAM_D10 L6
set_io SRAM_D11 M3
set_io SRAM_D12 L4
set_io SRAM_D13 L3
set_io SRAM_D14 K4
set_io SRAM_D15 K3

set_io SRAM_CE  M7
set_io SRAM_WE  T7
set_io SRAM_OE  L5
set_io SRAM_LB  J4
set_io SRAM_UB  J3

set_io HRAM_CK   N10
# set_io HRAM_RWDS P8  # SRAM_A18
# set_io HRAM_DQ0  T2  # SRAM_D0
# set_io HRAM_DQ1  R3  # SRAM_D1
# set_io HRAM_DQ2  T3  # SRAM_D2
# set_io HRAM_DQ3  R4  # SRAM_D3
# set_io HRAM_DQ4  R5  # SRAM_D4
# set_io HRAM_DQ5  T5  # SRAM_D5
# set_io HRAM_DQ6  R6  # SRAM_D6
# set_io HRAM_DQ7  T6  # SRAM_D7
# set_io HRAM_CS2n P10 # SRAM_A17
""")

icosoc_mk["10-top"].append("")

icosoc_mk["10-top"].append("ICOSOC_ROOT ?= %s" % basedir)
icosoc_mk["10-top"].append("RISCV_TOOLS_PREFIX ?= /opt/riscv32i%s%s/bin/riscv32-unknown-elf-" %
        ("m" if enable_muldiv_isa else "", "c" if enable_compressed_isa else ""))

if enable_flashpmem:
    icosoc_mk["10-top"].append("LDSCRIPT ?= %s/common/riscv_flash.ld" % basedir)
else:
    icosoc_mk["10-top"].append("LDSCRIPT ?= %s/common/riscv_orig.ld" % basedir)

icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("ifeq ($(shell bash -c 'type -p icoprog'),)")
icosoc_mk["10-top"].append("SSH_RASPI ?= ssh pi@raspi")
icosoc_mk["10-top"].append("else")
icosoc_mk["10-top"].append("SSH_RASPI ?= sh -c")
icosoc_mk["10-top"].append("endif")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("help:")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Building FPGA bitstream and program:\"")
icosoc_mk["10-top"].append("\t@echo \"   make prog_sram\"")
icosoc_mk["10-top"].append("\t@echo \"   make prog_flash\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Resetting FPGA (prevent boot from flash):\"")
icosoc_mk["10-top"].append("\t@echo \"   make reset_halt\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Resetting FPGA (load image from flash):\"")
icosoc_mk["10-top"].append("\t@echo \"   make reset_boot\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Erasing image from flash (erase first sector):\"")
icosoc_mk["10-top"].append("\t@echo \"   make reset_flash\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Build and upload FPGA + application image:\"")
icosoc_mk["10-top"].append("\t@echo \"   make run\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Upload FPGA (no rebuild) + application image:\"")
icosoc_mk["10-top"].append("\t@echo \"   make softrun\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Console session (close with Ctrl-D):\"")
icosoc_mk["10-top"].append("\t@echo \"   make console\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Download debug trace (to 'debug.vcd'):\"")
icosoc_mk["10-top"].append("\t@echo \"   make debug\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Run testbench and write trace (to 'testbench.vcd'):\"")
icosoc_mk["10-top"].append("\t@echo \"   make testbench_vcd\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("\t@echo \"Run testbench without writing VCD trace file:\"")
icosoc_mk["10-top"].append("\t@echo \"   make testbench_novcd\"")
icosoc_mk["10-top"].append("\t@echo \"\"")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("prog_sram: icosoc.bin")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -p' < icosoc.bin")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("prog_flash: icosoc.bin appimage.hex")
icosoc_mk["10-top"].append("\tpython3 %s/common/flashbin.py" % basedir)
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -f' < icosoc.bin")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -O8 -f' < appimage_lo.bin")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -O16 -f' < appimage_hi.bin")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("reset_halt:")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -R'")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("reset_flash:")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\tdd if=/dev/zero bs=1K count=64 | $(SSH_RASPI) 'icoprog -f'")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("reset_boot:")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -b'")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -Zr2'")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("run: icosoc.bin appimage.hex")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -p' < icosoc.bin")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -zZc2' < appimage.hex")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("softrun: appimage.hex")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -p' < icosoc.bin")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -zZc2' < appimage.hex")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("console:")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'icoprog -c2'")
icosoc_mk["10-top"].append("")
icosoc_mk["10-top"].append("debug:")
icosoc_mk["10-top"].append("\tgrep '// debug_.*->' icosoc.v")
icosoc_mk["10-top"].append("\t$(SSH_RASPI) 'killall -9 icoprog || true'")
icosoc_mk["10-top"].append("\tsedexpr=\"$$( grep '// debug_.*->' icosoc.v | sed 's,.*// \(debug_\),s/\\1,; s, *-> *, /,; s, *$$, /;,;'; )\"; \\")
icosoc_mk["10-top"].append("\t\t\t$(SSH_RASPI) \"icoprog -V $$( grep '// debug_.*->' icosoc.v | wc -l; )\" | sed -e \"$$sedexpr\" > debug.vcd")

icosoc_ys["10-readvlog"].append("read_verilog -D ICOSOC icosoc.v")
icosoc_ys["10-readvlog"].append("read_verilog -D ICOSOC %s/common/picorv32.v" % basedir)
icosoc_ys["10-readvlog"].append("read_verilog -D ICOSOC %s/common/icosoc_crossclkfifo.v" % basedir)
icosoc_ys["10-readvlog"].append("read_verilog -D ICOSOC %s/common/icosoc_debugger.v" % basedir)
icosoc_ys["10-readvlog"].append("read_verilog -D ICOSOC %s/common/icosoc_flashmem.v" % basedir)
icosoc_ys["10-readvlog"].append("read_verilog -D ICOSOC %s/common/icosoc_raspif.v" % basedir)
icosoc_ys["50-synthesis"].append("synth_ice40 -top icosoc -blif icosoc.blif")

icosoc_mk["50-synthesis"].append("icosoc.blif: icosoc.v icosoc.ys firmware_seed.hex")
icosoc_mk["50-synthesis"].append("\tyosys -l icosoc.log -v3 icosoc.ys")

icosoc_mk["50-synthesis"].append("icosoc.asc: icosoc.blif icosoc.pcf")
icosoc_mk["50-synthesis"].append("\tset -x; for seed in 1234 2345 3456 4567 5678 6789 7890; do \\")
icosoc_mk["50-synthesis"].append("\t\tarachne-pnr -s $$seed -d 8k -p icosoc.pcf -o icosoc.new_asc icosoc.blif && \\")
icosoc_mk["50-synthesis"].append("\t\ticetime -c 20 -d hx8k -tr icosoc.rpt icosoc.new_asc && exit 0; \\")
icosoc_mk["50-synthesis"].append("\tdone; false")
icosoc_mk["50-synthesis"].append("\tmv icosoc.new_asc icosoc.asc")

icosoc_mk["50-synthesis"].append("icosoc.bin: icosoc.asc firmware_seed.hex firmware.hex")
icosoc_mk["50-synthesis"].append("\ticebram firmware_seed.hex firmware.hex < icosoc.asc | icepack > icosoc.new_bin")
icosoc_mk["50-synthesis"].append("\tmv icosoc.new_bin icosoc.bin")

tbfiles = set()
tbfiles.add("icosoc.v")
tbfiles.add("testbench.v")
tbfiles.add("%s/common/picorv32.v" % basedir)
tbfiles.add("%s/common/icosoc_crossclkfifo.v" % basedir)
tbfiles.add("%s/common/icosoc_debugger.v" % basedir)
tbfiles.add("%s/common/icosoc_flashmem.v" % basedir)
tbfiles.add("%s/common/icosoc_raspif.v" % basedir)
tbfiles.add("%s/common/sim_sram.v" % basedir)
tbfiles.add("%s/common/sim_spiflash.v" % basedir)
tbfiles |= modvlog

icosoc_mk["60-simulation"].append("testbench: %s" % (" ".join(tbfiles)))
icosoc_mk["60-simulation"].append("\tiverilog -D ICOSOC -D TESTBENCH -o testbench %s $(shell yosys-config --datdir/ice40/cells_sim.v)" % (" ".join(tbfiles)))

icosoc_mk["60-simulation"].append("testbench_vcd: testbench firmware.hex appimage.hex")
icosoc_mk["60-simulation"].append("\tvvp -N testbench +vcd")

icosoc_mk["60-simulation"].append("testbench_novcd: testbench firmware.hex appimage.hex")
icosoc_mk["60-simulation"].append("\tvvp -N testbench")

if not opt.custom_firmware:
    icosoc_mk["70-firmware"].append("firmware.elf: %s/common/firmware.S %s/common/firmware.c %s/common/firmware.lds icosoc.cfg" % (basedir, basedir, basedir))
    icosoc_mk["70-firmware"].append(("\t$(RISCV_TOOLS_PREFIX)gcc -Os %s%s%s-march=rv32i -ffreestanding " +
            "-nostdlib -Wall -o firmware.elf %s/common/firmware.S %s/common/firmware.c \\") % (
            "-DFLASHPMEM " if enable_flashpmem else "",
            "-DNOFLASHBOOT " if enable_noflashboot else "",
            "-DFASTFLASHBOOT " if enable_fastflashboot else "",
            basedir, basedir))
    icosoc_mk["70-firmware"].append("\t\t\t--std=gnu99 -Wl,-Bstatic,-T,%s/common/firmware.lds,-Map,firmware.map,--strip-debug -lgcc" % basedir)
    icosoc_mk["70-firmware"].append("\tchmod -x firmware.elf")

icosoc_mk["70-firmware"].append("firmware.bin: firmware.elf")
icosoc_mk["70-firmware"].append("\t$(RISCV_TOOLS_PREFIX)objcopy -O binary firmware.elf firmware.bin")
icosoc_mk["70-firmware"].append("\tchmod -x firmware.bin")

icosoc_mk["70-firmware"].append("firmware.hex: %s/common/makehex.py firmware.bin" % basedir)
icosoc_mk["70-firmware"].append("\tpython3 %s/common/makehex.py firmware.bin 1024 > firmware.hex" % basedir)
icosoc_mk["70-firmware"].append("\t@echo \"Firmware size: $$(grep .. firmware.hex | wc -l) / $$(wc -l < firmware.hex)\"")

icosoc_mk["70-firmware"].append("firmware_seed.hex:")
icosoc_mk["70-firmware"].append("\ticebram -g 32 1024 > firmware_seed.hex")

icosoc_mk["90-extradeps"].append("icosoc.v: icosoc.mk")
icosoc_mk["90-extradeps"].append("icosoc.ys: icosoc.mk")
icosoc_mk["90-extradeps"].append("icosoc.pcf: icosoc.mk")
icosoc_mk["90-extradeps"].append("icosoc.mk: icosoc.cfg")
icosoc_mk["90-extradeps"].append("icosoc.mk: %s/icosoc.py" % basedir)
icosoc_mk["90-extradeps"].append("icosoc.mk: %s/mod_*/*.py" % basedir)
icosoc_mk["90-extradeps"].append("icosoc.blif: %s/common/*.v" % basedir)
icosoc_mk["90-extradeps"].append("icosoc.blif: %s/mod_*/*.v" % basedir)

filelist = [
    "firmware.bin firmware.elf firmware_seed.hex firmware.hex firmware.map",
    "icosoc.mk icosoc.ys icosoc.pcf icosoc.v icosoc.h icosoc.c icosoc.ld",
    "icosoc.blif icosoc.asc icosoc.bin icosoc.log icosoc.rpt debug.vcd",
    "testbench testbench.v testbench.vcd",
    "appimage_lo.bin appimage_hi.bin",
]

if opt.no_clean_target:
    l = "CLEAN ="
    for f in filelist:
        icosoc_mk["95-clean"].append(l + ' \\')
        l = '    ' + f
    icosoc_mk["95-clean"].append(l)
else:
    icosoc_mk["95-clean"].append("clean::")
    for f in filelist :
        icosoc_mk["95-clean"].append("\trm -f %s" % f)

if not opt.no_clean_target:
    icosoc_mk["99-special"].append(".PHONY: clean")
icosoc_mk["99-special"].append(".SECONDARY:")

icosoc_h.append("""
#endif /* ICOSOC_H */
""");

testbench["10-header"].append("""
module testbench;

    reg clk = 1;
    always #5 clk = ~clk;
""");

for net in sorted(iowires):
    testbench["20-ionets"].append("    wire %s;" % net)
testbench["20-ionets"].append("")

testbench["30-inst"].append("    icosoc uut (")
for net in sorted(iowires):
    testbench["30-inst"].append("        .%s(%s)," % (net, net))
testbench["30-inst"][-1] = testbench["30-inst"][-1].rstrip(",")
testbench["30-inst"].append("    );")
testbench["30-inst"].append("")

testbench["30-inst"].append("    sim_sram sram (")
for net in sorted(iowires):
    if net.startswith("SRAM_"):
        testbench["30-inst"].append("        .%s(%s)," % (net, net))
testbench["30-inst"][-1] = testbench["30-inst"][-1].rstrip(",")
testbench["30-inst"].append("    );")
testbench["30-inst"].append("")

testbench["30-inst"].append("    sim_spiflash spiflash (")
for net in sorted(iowires):
    if net.startswith("SPI_FLASH_"):
        testbench["30-inst"].append("        .%s(%s)," % (net, net))
testbench["30-inst"][-1] = testbench["30-inst"][-1].rstrip(",")
testbench["30-inst"].append("    );")
testbench["30-inst"].append("")

testbench["90-footer"].append("""
    assign CLKIN = clk;

    wire [8:0] raspi_din;
    reg [8:0] raspi_dout = 9'b z_zzzz_zzzz;
    reg raspi_clk = 0;
    reg raspi_dir = 0;

    assign {RASPI_11, RASPI_12, RASPI_15, RASPI_16, RASPI_19, RASPI_21, RASPI_26, RASPI_35, RASPI_36} = raspi_dout;
    assign raspi_din = {RASPI_11, RASPI_12, RASPI_15, RASPI_16, RASPI_19, RASPI_21, RASPI_26, RASPI_35, RASPI_36};
    assign RASPI_40 = raspi_clk, RASPI_38 = raspi_dir;

    task raspi_send_word(input [8:0] data);
        begin
            raspi_clk <= 0;
            raspi_dir <= 1;
            raspi_dout <= {1'b0, data};

            repeat (5) @(posedge clk);
            raspi_clk <= 1;
            repeat (10) @(posedge clk);
            raspi_clk <= 0;
            repeat (5) @(posedge clk);
        end
    endtask

    task raspi_recv_word(output [8:0] data);
        begin
            raspi_clk <= 0;
            raspi_dir <= 0;
            raspi_dout <= 9'b z_zzzz_zzzz;

            repeat (5) @(posedge clk);
            raspi_clk <= 1;
            repeat (10) @(posedge clk);
            data = raspi_din;
            raspi_clk <= 0;
            repeat (5) @(posedge clk);
        end
    endtask

    reg [7:0] raspi_current_ep;
    reg [8:0] raspi_current_word;

    event appimage_ready;

    initial begin
        @(appimage_ready);

        if ($test$plusargs("vcd")) begin
            $dumpfile("testbench.vcd");
            $dumpvars(0, testbench);
        end

        $display("-- Printing console messages --");
        forever begin
            raspi_recv_word(raspi_current_word);
            if (raspi_current_word[8]) begin
                raspi_current_ep = raspi_current_word[7:0];
            end else if (raspi_current_ep == 2) begin
                $write("%c", raspi_current_word[7:0]);
                $fflush();
            end
        end
    end

    initial begin
        @(appimage_ready);
        repeat (100) @(posedge clk);
        @(posedge uut.cpu_trap);
        repeat (100) @(posedge clk);
        $display("-- CPU Trapped --");
        $finish;
    end

    initial begin:appimgage_init
        reg [7:0] appimage [0:16*1024*1024-1];
        integer i;

        $display("-- Loading appimage --");

        $readmemh("appimage.hex", appimage);

        for (i = 0; i < 'h10000; i=i+1) begin
            sram.sram_memory[(i + 'h8000) % 'h10000][7:0] = appimage['h10000 + 2*i];
            sram.sram_memory[(i + 'h8000) % 'h10000][15:8] = appimage['h10000 + 2*i + 1];
        end

        for (i = 1*1024*1024; i < 2*1024*1024; i=i+1) begin
            spiflash.memory[i] = appimage[i];
        end

        -> appimage_ready;
    end
endmodule
""");

with open(basedir + "/common/syscalls.c", "r") as f:
    for line in f: icosoc_c.append(line.rstrip())

def write_outfile_dict(filename, data, comment_start = None):
    with open(filename, "w") as f:
        if comment_start is not None:
            print("%s #### This file is auto-generated from icosoc.py. Do not edit! ####" % comment_start, file=f)
            print("", file=f)
        for section, lines in sorted(data.items()):
            if comment_start is not None:
                print("%s ++ %s ++" % (comment_start, section), file=f)
            for line in lines: print(line, file=f)

def write_outfile_list(filename, data, comment_start = None):
    with open(filename, "w") as f:
        if comment_start is not None:
            print("%s #### This file is auto-generated from icosoc.py. Do not edit! ####" % comment_start, file=f)
            print("", file=f)
        for line in data:
            print(line, file=f)

write_outfile_dict("icosoc.mk", icosoc_mk, "#")
write_outfile_dict("icosoc.ys", icosoc_ys, "#")
write_outfile_dict("icosoc.pcf", icosoc_pcf, "#")
write_outfile_dict("icosoc.v", icosoc_v, "//")
write_outfile_dict("testbench.v", testbench, "//")
write_outfile_list("icosoc.h", icosoc_h, "//")
write_outfile_list("icosoc.c", icosoc_c, "//")

