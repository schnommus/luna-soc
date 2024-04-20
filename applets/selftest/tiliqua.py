# Copyright (c) 2024 Sebastian Holzapfel <me@sebholzapfel.com>
# SPDX-License-Identifier: BSD-3-Clause

""" tiliqua platform definitions. CAR includes extra 12.288MHz PLL for audio clock. """

from amaranth import *
from amaranth.build import *
from amaranth.vendor import LatticeECP5Platform

from amaranth_boards.resources import *

from luna.gateware.platform.core import LUNAPlatform

class _TiliquaPlatform(LatticeECP5Platform):
    device      = "LFE5U-45F"
    package     = "BG256"
    speed       = "7"
    default_clk = "clk48"
    default_rst = "rst"

    #
    # Preferred DRAM bus I/O (de)-skewing constants.
    #
    ram_timings = dict(
        # Set max skew to meet IO setup times
        # TODO: remove this & use the PLL to produce a 90degree clock signal instead.
        clock_skew = 127
    )

    resources   = [
        # BOOTSEL (shared)
        Resource("rst", 0, PinsN("C4", dir="i"), Attrs(IO_TYPE="LVCMOS33")),

        # 48MHz master
        Resource("clk48", 0, Pins("A8", dir="i"), Clock(48e6), Attrs(IO_TYPE="LVCMOS33")),

        # PROGRAMN, used to trigger self-reconfiguration
        Resource("self_program", 0, PinsN("T13", dir="o"), Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")),

        # LEDs
        Resource("led", 0, PinsN("B7", dir="o"),  Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 1, PinsN("A3", dir="o"),  Attrs(IO_TYPE="LVCMOS33")),

        # Button B
        # Resource("button_b", 0, PinsN("C4", dir="i"),  Attrs(IO_TYPE="LVCMOS33")),

        # RP2040 bridge
        UARTResource(0,
            rx="A4", tx="B4",
            attrs=Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")
        ),

        # MIDI I/O
        UARTResource(1,
            rx="D5", tx="B8",
            attrs=Attrs(IO_TYPE="LVCMOS33", PULLMODE="UP")
        ),

        # USB
        ULPIResource("target_phy", 0,
            data="D6 D4 E4 A5 B5 A6 B6 B3",
            clk="D7", clk_dir="o", dir="A2", nxt="C5",
            stp="C6", rst="C7", rst_invert=True,
            attrs=Attrs(IO_TYPE="LVCMOS33")),

        # FFC connector to eurorack-pmod on the back.
        Resource("audio_ffc", 0,
            Subsignal("sdin1",  Pins("D8",  dir="o")),
            Subsignal("sdout1", Pins("C9",  dir="i")),
            Subsignal("lrck",   Pins("C10", dir="o")),
            Subsignal("bick",   Pins("D9",  dir="o")),
            Subsignal("mclk",   Pins("B11", dir="o")),
            Subsignal("pdn",    Pins("C11", dir="o")),
            Subsignal("i2c_sda",    Pins("D13", dir="io")),
            Subsignal("i2c_scl",    Pins("C13", dir="io")),
        ),

        # Use LUNA -- interface/flash.py for this
        Resource("spi_flash", 0,
            # SCK needs to go through a USRMCLK instance.
            Subsignal("sdi",  Pins("T8",  dir="o")),
            Subsignal("sdo",  Pins("T7",  dir="i")),
            Subsignal("cs",   PinsN("N8", dir="o")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        # HyperRAM
        Resource("ram", 0,
            Subsignal("clk",   DiffPairs("C3", "D3", dir="o"), Attrs(IO_TYPE="LVCMOS33D")),
            Subsignal("dq",    Pins("F2 B1 C2 E1 E3 E2 F3 G4", dir="io")),
            Subsignal("rwds",  Pins( "D1", dir="io")),
            Subsignal("cs",    Pins("B2", dir="o")),
            Subsignal("reset", PinsN("C1", dir="o")),
            Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST")
        ),
    ]

    connectors  = [
        Connector("pmod", 0, "A9 A13 B14 C14 - - B9 B13 A14 D14 - -"),
        Connector("pmod", 1, "A10 B15 C15 C16 - - B10 A15 B16 D16 - -"),
    ]

class TiliquaDomainGenerator(Elaboratable):
    """ Clock generator for Tiliqua platform. """

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):

        self.phase_sel  = Signal(2, reset = 0)
        self.phase_dir  = Signal(1, reset = 1)
        self.phase_step = Signal(1, reset = 1)
        self.phase_load = Signal(1, reset = 1)

        self.slip_hr2x   = Signal(1, reset = 0)
        self.slip_hr2x90 = Signal(1, reset = 0)


    def elaborate(self, platform):
        m = Module()

        # Create our domains.
        m.domains.hr2x      = ClockDomain()
        m.domains.hr2x_90   = ClockDomain()
        m.domains.hr     = ClockDomain()
        m.domains.hr_90  = ClockDomain()
        m.domains.sync   = ClockDomain()
        m.domains.usb    = ClockDomain()
        m.domains.fast   = ClockDomain()
        m.domains.audio  = ClockDomain()
        m.domains.raw48  = ClockDomain()


        clk48 = platform.request(platform.default_clk, dir='i').i
        reset  = platform.request(platform.default_rst, dir='i').i
        #reset  = Signal(1, reset=0)

        # ecppll -i 48 --clkout0 120 --clkout1 120 --clkout2 120 --phase2 90

        m.d.comb += [
            ClockSignal("raw48").eq(clk48),
        ]

        feedback120 = Signal()
        locked120   = Signal()
        m.submodules.pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=clk48,

                # Generated clock outputs.
                o_CLKOP=feedback120,
                o_CLKOS=ClockSignal("hr2x"),
                o_CLKOS2=ClockSignal("hr2x_90"),

                # Status.
                o_LOCK=locked120,

                # PLL parameters...
                p_PLLRST_ENA="ENABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_OUTDIVIDER_MUXB="DIVB",
                p_OUTDIVIDER_MUXC="DIVC",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKI_DIV=2,
                p_CLKOP_ENABLE="ENABLED",
                p_CLKOP_DIV=5,
                p_CLKOP_CPHASE=2,
                p_CLKOP_FPHASE=0,
                p_CLKOS_ENABLE="ENABLED",
                p_CLKOS_DIV=5,
                p_CLKOS_CPHASE=2,
                p_CLKOS_FPHASE=0,
                p_CLKOS2_ENABLE="ENABLED",
                p_CLKOS2_DIV=5,
                p_CLKOS2_CPHASE=3,
                p_CLKOS2_FPHASE=2,
                p_FEEDBK_PATH="CLKOP",
                p_CLKFB_DIV=5,

                # Internal feedback.
                i_CLKFB=feedback120,

                # Control signals.
                i_RST=reset,
                i_PHASESEL0=self.phase_sel[0], # TODO: check index?
                i_PHASESEL1=self.phase_sel[1],
                i_PHASEDIR=self.phase_dir,
                i_PHASESTEP=self.phase_step,
                i_PHASELOADREG=self.phase_load,
                i_STDBY=0,
                i_PLLWAKESYNC=0,

                # Output Enables.
                i_ENCLKOP=0,
                i_ENCLKOS=0,
                i_ENCLKOS2=0,
                i_ENCLKOS3=0,

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="48",
                a_FREQUENCY_PIN_CLKOP="120",
                a_FREQUENCY_PIN_CLKOS="120",
                a_FREQUENCY_PIN_CLKOS2="120",
                a_ICP_CURRENT="12",
                a_LPF_RESISTOR="8"
        )


        # ecppll -i 48 --clkout0 12.288 --highres --reset -f pll2.v
        # 12.288MHz for 256*Fs Audio domain (48KHz Fs)

        feedback12  = Signal()
        locked12    = Signal()
        m.submodules.audio_pll = Instance("EHXPLLL",

                # Status.
                o_LOCK=locked12,

                # PLL parameters...
                p_PLLRST_ENA="ENABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_OUTDIVIDER_MUXB="DIVB",
                p_OUTDIVIDER_MUXC="DIVC",
                p_OUTDIVIDER_MUXD="DIVD",

                p_CLKI_DIV = 5,
                p_CLKOP_ENABLE = "ENABLED",
                p_CLKOP_DIV = 32,
                p_CLKOP_CPHASE = 9,
                p_CLKOP_FPHASE = 0,
                p_CLKOS_ENABLE = "ENABLED",
                p_CLKOS_DIV = 50,
                p_CLKOS_CPHASE = 0,
                p_CLKOS_FPHASE = 0,
                p_FEEDBK_PATH = "CLKOP",
                p_CLKFB_DIV = 2,

                # Clock in.
                i_CLKI=clk48,

                # Internal feedback.
                i_CLKFB=feedback12,

                # Control signals.
                i_RST=reset,
                i_PHASESEL0=0,
                i_PHASESEL1=0,
                i_PHASEDIR=1,
                i_PHASESTEP=1,
                i_PHASELOADREG=1,
                i_STDBY=0,
                i_PLLWAKESYNC=0,

                # Output Enables.
                i_ENCLKOP=0,
                i_ENCLKOS2=0,

                # Generated clock outputs.
                o_CLKOP=feedback12,
                o_CLKOS=ClockSignal("audio"),

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="48",
                a_FREQUENCY_PIN_CLKOS="12.288",
                a_ICP_CURRENT="12",
                a_LPF_RESISTOR="8",
                a_MFG_ENABLE_FILTEROPAMP="1",
                a_MFG_GMCREF_SEL="2"
        )

        m.submodules.clkdiv_hr = Instance("CLKDIVF",
            p_GSR="DISABLED",
            p_DIV="2.0",

            i_CLKI=ClockSignal("hr2x"),
            i_RST=~locked120,
            i_ALIGNWD=self.slip_hr2x,

            o_CDIVX=ClockSignal("hr"),
        )

        m.submodules.clkdiv_hr_90 = Instance("CLKDIVF",
            p_GSR="DISABLED",
            p_DIV="2.0",

            i_CLKI=ClockSignal("hr2x_90"),
            i_RST=~locked120,
            i_ALIGNWD=self.slip_hr2x90,

            o_CDIVX=ClockSignal("hr_90"),
        )

        # Derived clocks and resets
        m.d.comb += [
            ClockSignal("usb")      .eq(ClockSignal("hr")),
            ClockSignal("sync")     .eq(ClockSignal("hr")),
            ClockSignal("fast")     .eq(ClockSignal("hr")),

            ResetSignal("sync")     .eq(~locked120),
            ResetSignal("fast")     .eq(~locked120),
            ResetSignal("usb")      .eq(~locked120),

            ResetSignal("hr")       .eq(~locked120),
            ResetSignal("hr_90")    .eq(~locked120),
            ResetSignal("hr2x")     .eq(~locked120),
            ResetSignal("hr2x_90")  .eq(~locked120),

            ResetSignal("audio")   .eq(~locked12),
        ]

        return m

class TiliquaPlatform(_TiliquaPlatform, LUNAPlatform):
    name                   = "Tiliqua (45F)"
    clock_domain_generator = TiliquaDomainGenerator
    default_usb_connection = "ulpi"
