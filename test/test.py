# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, FallingEdge, Timer

import scripts.qspi_sim as qspi_sim

def set_4bit_io(dut, value):
    dut.uio_in[3].value = (value >> 0) & 1  # IO_0
    dut.ui_in[2].value  = (value >> 1) & 1  # IO_1
    dut.ui_in[3].value  = (value >> 2) & 1  # IO_2
    dut.uio_in[6].value = (value >> 3) & 1  # IO_3

def get_rgb(output_value):
    # red is bits 2,1,0
    # green is bits 5,4,3
    # blue is bits 7,6
    red = ((output_value & 0b100) >> 2) << 2 | ((output_value & 0b10) >> 1) << 1 | (output_value & 0b1)
    green = ((output_value & 0b100000) >> 5) << 2 | ((output_value & 0b10000) >> 4) << 1 | ((output_value & 0b1000) >> 3)
    blue = ((output_value & 0b10000000) >> 7) << 1 | ((output_value & 0b1000000) >> 6)

    return (red << 5) | (green << 2) | blue

@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")

    # Set the clock period to 10 us (100 KHz)
    clock = Clock(dut.clk, 40, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.uo_out.value = 0
    dut.uio_out.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1

    dut._log.info("Test project behavior")

    dut._log.info("Awaiting CS Low")
    while dut.uio_out[2] != 0:
        await FallingEdge(dut.clk)

    instruction = 0x6b
    dut._log.info("Sending QSPI Instruction")

    for i in range(8):
        dataOutput = dut.uio_out[3].value
        if (instruction & (1 << (7-i))): # 1
            assert dataOutput == 1, f"Expected bit {i} to be 1, got {dataOutput}"
        else:  # 0
            assert dataOutput == 0, f"Expected bit {i} to be 0, got {dataOutput}"
        await FallingEdge(dut.clk)

    dut._log.info("Instruction code send successfully, Sending dummy data")

    for i in range(32):
        # Check if hold pin is held high
        outputEnable = dut.uio_oe[6].value
        dataOutput = dut.uio_out[6].value
        assert outputEnable == 1, f"Expected output enable to be high at bit {i}, got {outputEnable}"
        assert dataOutput == 1, f"Expected hold pin to be high at bit {i}, got {dataOutput}"
        if (i < 31):
            await FallingEdge(dut.clk)

    await FallingEdge(dut.clk)  # Send the simulated flash IC Data
    set_4bit_io(dut, int(qspi_sim.clock_data()))
    outputEnable = dut.uio_oe[6].value
    assert outputEnable == 0, f"Expected output enable to be low at end of instruction, got {outputEnable}"
    dut._log.info("QSPI instruction sent successfully")

    with open("resources/data.bin", "rb") as f:
        data = f.read()

    output_file = open("resources/output.bin", "wb")

    total_nibbles = len(data) * 2

    leading_blank_count = 0

    # we count up to 640 and then it is blanking, we halt output to file for 160 clocks
    current_blank_width = 1

    # we count up to 480 and then it is blanking, we halt output to file for 45 rows
    current_blank_height = 1
    for nibble_index in range(total_nibbles):
        # Wait until SCLK goes high (i.e., ready to receive next nibble)
        timeout = 50000
        timeout_cnt = 0

        while True:
            await RisingEdge(dut.clk)
            sclk_enabled = (dut.uio_out[4] == 1)
            await FallingEdge(dut.clk)
            
            # wait for the leading blank region to finish
            if(leading_blank_count > 35317):
                colour = get_rgb(dut.uo_out.value)
                if(current_blank_width <= 640 and current_blank_height <= 480):
                    output_file.write(int(colour).to_bytes(1, 'big'))

                current_blank_width += 1
                if(current_blank_width == 801):
                    # reset width count
                    current_blank_width = 1
                    # increment height count
                    current_blank_height += 1
                

                if(current_blank_height == 526):
                    # reset height count
                    current_blank_height = 1

            else:
                leading_blank_count += 1
            set_4bit_io(dut, 0)

            if sclk_enabled:
                break

            timeout_cnt += 1
            if timeout_cnt >= timeout:
                raise cocotb.result.TestFailure(f"Timeout waiting for SCLK on nibble {nibble_index}")

        # Provide next nibble of data
        set_4bit_io(dut, int(qspi_sim.clock_data()))

    dut._log.info("All data from data.bin successfully streamed.")
    await FallingEdge(dut.clk)
    set_4bit_io(dut, 0)
    await ClockCycles(dut.clk, 800*7) # wait for buffer to be emptied

    await ClockCycles(dut.clk, 100)  # Observe the Reset behaviour

    assert True

