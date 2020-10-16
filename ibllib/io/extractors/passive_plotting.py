#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @Author: Niccolò Bonacchi
# @Date: Friday, October 16th 2020, 5:53:15 pm
# PLOTTING
from ibllib.plots import color_cycle, squares, vertical_lines


def plot_rfmapping(times_interp_RF, ax=None):
    if ax is None:
        f, ax = plt.subplots(1, 1)

    vertical_lines(
        times_interp_RF, ymin=0, ymax=1, color=color_cycle(9), ax=ax, label="RFframe_times"
    )

    ax.legend()


def plot_sync_channels(sync, sync_map, ax=None):
    # Plot all sync pulses
    if ax is None:
        f, ax = plt.subplots(1, 1)
    for i, device in enumerate(["frame2ttl", "audio", "bpod"]):
        sy = ephys_fpga._get_sync_fronts(sync, sync_map[device])  # , tmin=t_start_passive)
        squares(sy["times"], sy["polarities"], yrange=[0.1 + i, 0.9 + i], color="k", ax=ax)


def plot_passive_periods(t_start_passive, t_starts, t_ends, ax=None):
    if ax is None:
        f, ax = plt.subplots(1, 1)
    # Update plot
    vertical_lines(
        np.r_[t_start_passive, t_starts, t_ends],
        ymin=-1,
        ymax=4,
        color=color_cycle(0),
        ax=ax,
        label="spacers",
    )
    ax.legend()


def plot_gabor_times(passiveGabor_df, ax=None):
    if ax is None:
        f, ax = plt.subplots(1, 1)
    # Update plot
    vertical_lines(
        passiveGabor_df["start"].values,
        ymin=0,
        ymax=1,
        color=color_cycle(1),
        ax=ax,
        label="GaborOn_times",
    )
    vertical_lines(
        passiveGabor_df["stop"].values,
        ymin=0,
        ymax=1,
        color=color_cycle(2),
        ax=ax,
        label="GaborOff_times",
    )
    ax.legend()


def plot_valve_times(passiveValve_intervals, ax=None):
    if ax is None:
        f, ax = plt.subplots(1, 1)
    # Update the plot
    vertical_lines(
        passiveValve_intervals[:, 0],
        ymin=2,
        ymax=3,
        color=color_cycle(3),
        ax=ax,
        label="ValveOn_times",
    )
    vertical_lines(
        passiveValve_intervals[:, 1],
        ymin=2,
        ymax=3,
        color=color_cycle(4),
        ax=ax,
        label="ValveOff_times",
    )
    ax.legend()


def plot_audio_times(passiveTone_intervals, passiveNoise_intervals, ax=None):
    if ax is None:
        f, ax = plt.subplots(1, 1)
    # Look at it
    vertical_lines(
        passiveTone_intervals[:, 0],
        ymin=1,
        ymax=2,
        color=color_cycle(5),
        ax=ax,
        label="toneOn_times",
    )
    vertical_lines(
        passiveTone_intervals[:, 1],
        ymin=1,
        ymax=2,
        color=color_cycle(6),
        ax=ax,
        label="toneOff_times",
    )
    vertical_lines(
        passiveNoise_intervals[:, 0],
        ymin=1,
        ymax=2,
        color=color_cycle(7),
        ax=ax,
        label="noiseOn_times",
    )
    vertical_lines(
        passiveNoise_intervals[:, 1],
        ymin=1,
        ymax=2,
        color=color_cycle(8),
        ax=ax,
        label="noiseOff_times",
    )

    ax.legend()
    # plt.show()
