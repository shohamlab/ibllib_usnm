from iblutil.numerical import ismember
from brainbox.processing import bincount2D
import numpy as np


def find_trial_ids(trials, side='all', choice='all', order='trial num', sort='idx',
                   contrast=(1, 0.5, 0.25, 0.125, 0.0625, 0), event=None):
    """
    Finds trials that match criterion
    :param trials: trials object. Must contain attributes contrastLeft, contrastRight and
    feedbackType
    :param side: stimulus side, options are 'all', 'left' or 'right'
    :param choice: trial choice, options are 'all', 'correct' or 'incorrect'
    :param contrast: contrast of stimulus, pass in list/tuple of all contrasts that want to be
    considered e.g [1, 0.5] would only look for trials with 100 % and 50 % contrast
    :param order: how to order the trials, options are 'trial num' or 'reaction time'
    :param sort: how to sort the trials, options are 'side' (split left right trials), 'choice'
    (split correct incorrect trials), 'choice and side' (split left right and correct incorrect)
    :param event: trial event to align to (in order to remove nan trials for this event)
    :return: np.array of trial ids, list of dividers to indicate how trials are sorted
    """

    if event:
        idx = ~np.isnan(trials[event])
    else:
        idx = np.ones_like(trials['feedbackType'], dtype=bool)

    # TODO write tests for this
    # Find trials that have specified contrasts
    cont = np.bitwise_or(ismember(trials['contrastLeft'][idx], np.array(contrast))[0],
                         ismember(trials['contrastRight'][idx], np.array(contrast))[0])

    # Find different permutations of trials
    # correct right
    cor_r = np.where(
        np.bitwise_and(cont, np.bitwise_and(trials['feedbackType'][idx] == 1,
                                            np.isfinite(trials['contrastRight'][idx]))))[0]
    # correct left
    cor_l = np.where(
        np.bitwise_and(cont, np.bitwise_and(trials['feedbackType'][idx] == 1,
                                            np.isfinite(trials['contrastLeft'][idx]))))[0]
    # incorrect right
    incor_r = np.where(
        np.bitwise_and(cont, np.bitwise_and(trials['feedbackType'][idx] == -1,
                                            np.isfinite(trials['contrastRight'][idx]))))[0]
    # incorrect left
    incor_l = np.where(
        np.bitwise_and(cont, np.bitwise_and(trials['feedbackType'][idx] == -1,
                                            np.isfinite(trials['contrastLeft'][idx]))))[0]

    reaction_time = trials.response_times[idx] - trials.goCue_times[idx]

    def _order_by(_trials, order):
        # Returns subset of trials either ordered by trial number or by reaction time
        sorted_trials = np.sort(_trials)
        if order == 'trial num':
            return sorted_trials
        elif order == 'reaction time':
            sorted_reaction = np.argsort(reaction_time[sorted_trials])
            return sorted_trials[sorted_reaction]

    dividers = []

    # Find the trial id for all possible combinations
    if side == 'all' and choice == 'all':
        if sort == 'idx':
            trial_id = _order_by(np.r_[cor_r, cor_l, incor_r, incor_l], order)
        elif sort == 'choice':
            trial_id = np.r_[_order_by(np.r_[cor_l, cor_r], order),
                             _order_by(np.r_[incor_l, incor_r], order)]
            dividers.append(np.r_[cor_l, cor_r].shape[0])
        elif sort == 'side':
            trial_id = np.r_[_order_by(np.r_[cor_l, incor_l], order),
                             _order_by(np.r_[cor_r, incor_r], order)]
            dividers.append(np.r_[cor_l, incor_l].shape[0])
        elif sort == 'choice and side':
            trial_id = np.r_[_order_by(cor_l, order), _order_by(incor_l, order),
                             _order_by(cor_r, order), _order_by(incor_r, order)]
            dividers.append(cor_l.shape[0])
            dividers.append(np.r_[cor_l, incor_l].shape[0])
            dividers.append(np.r_[cor_l, incor_l, cor_r].shape[0])

    if side == 'left' and choice == 'all':
        if sort in ['idx', 'side']:
            trial_id = _order_by(np.r_[cor_l, incor_l], order)
        elif sort in ['choice', 'choice and side']:
            trial_id = np.r_[_order_by(cor_l, order), _order_by(incor_l, order)]
            dividers.append(cor_l.shape[0])

    if side == 'right' and choice == 'all':
        if sort in ['idx', 'side']:
            trial_id = _order_by(np.r_[cor_r, incor_r], order)
        elif sort in ['choice', 'choice and side']:
            trial_id = np.r_[_order_by(cor_r, order), _order_by(incor_r, order)]
            dividers.append(cor_r.shape[0])

    if side == 'all' and choice == 'correct':
        if sort in ['idx', 'choice']:
            trial_id = _order_by(np.r_[cor_l, cor_r], order)
        elif sort in ['side', 'choice and side']:
            trial_id = np.r_[_order_by(cor_l, order), _order_by(cor_r, order)]
            dividers.append(cor_l.shape[0])

    if side == 'all' and choice == 'incorrect':
        if sort in ['idx', 'choice']:
            trial_id = _order_by(np.r_[incor_l, incor_r], order)
        elif sort in ['side', 'choice and side']:
            trial_id = np.r_[_order_by(incor_l, order), _order_by(incor_r, order)]
            dividers.append(incor_l.shape[0])

    if side == 'left' and choice == 'correct':
        trial_id = _order_by(cor_l, order)

    if side == 'left' and choice == 'incorrect':
        trial_id = _order_by(incor_l, order)

    if side == 'right' and choice == 'correct':
        trial_id = _order_by(cor_r, order)

    if side == 'right' and choice == 'incorrect':
        trial_id = _order_by(incor_r, order)

    return trial_id, dividers


def get_event_aligned_raster(times, events, tbin=0.02, values=None, epoch=[-0.4, 1], bin=True):

    if bin:
        vals, bin_times, _ = bincount2D(times, np.ones_like(times), xbin=tbin, weights=values)
        vals = vals[0]
        t = np.arange(epoch[0], epoch[1] + tbin, tbin)
    else:
        vals = values
        bin_times = times
        tbin = np.mean(np.diff(bin_times))
        t = np.arange(epoch[0], epoch[1], tbin)

    # remove nan trials
    events = events[~np.isnan(events)]
    intervals = np.c_[events + epoch[0], events + epoch[1]]

    # Remove any trials that are later than the last value in bin_times
    out_intervals = intervals[:, 1] > bin_times[-1]
    epoch_idx = np.searchsorted(bin_times, intervals)[np.invert(out_intervals)]

    for ep in range(np.median(epoch_idx[:, 1] - epoch_idx[:, 0]).astype(int) + 1):
        if ep == 0:
            event_raster = (vals[epoch_idx[:, 0] + ep]).astype(float)
        else:
            event_raster = np.c_[event_raster, vals[epoch_idx[:, 0] + ep]]

    # Find any trials that are less than the first value time and fill with nans (case for example
    # where spiking of cluster doesn't start till after start of first trial due to settling of
    # brain)
    event_raster[intervals[np.invert(out_intervals), 0] < bin_times[0]] = np.nan

    # Add back in the trials that were later than last value with nans
    if np.sum(out_intervals) > 0:
        print('doing the extra nans')
        event_raster = np.r_[event_raster, np.full((np.sum(out_intervals),
                                                    event_raster.shape[1]), np.nan)]
        assert(event_raster.shape[0] == intervals.shape[0])

    return event_raster, t


def get_psth(raster, trial_ids=None):
    if trial_ids is None:
        mean = np.nanmean(raster, axis=0)
        err = np.nanstd(raster, axis=0) / np.sqrt(raster.shape[0])
    else:
        raster = filter_by_trial(raster, trial_ids)
        mean = np.nanmean(raster, axis=0)
        err = np.nanstd(raster, axis=0) / np.sqrt(raster.shape[0])

    return mean, err


def filter_by_trial(raster, trial_id):
    return raster[trial_id, :]


def filter_correct_incorrect_left_right(trials, event_raster, event, order='trial num'):
    trials_sorted, div = find_trial_ids(trials, sort='choice and side', event=event, order=order)
    trials_lc, _ = find_trial_ids(trials, side='left', choice='correct', event=event, order=order)
    trials_li, _ = find_trial_ids(trials, side='left', choice='incorrect', event=event,
                                  order=order)
    trials_rc, _ = find_trial_ids(trials, side='right', choice='correct', event=event, order=order)
    trials_ri, _ = find_trial_ids(trials, side='right', choice='incorrect', event=event,
                                  order=order)

    psth = dict()
    mean, err = get_psth(event_raster, trials_lc)
    psth['left_correct'] = {'vals': mean, 'err': err,
                            'linestyle': {'color': 'r'}}
    mean, err = get_psth(event_raster, trials_li)
    psth['left_incorrect'] = {'vals': mean, 'err': err,
                              'linestyle': {'color': 'r', 'linestyle': 'dashed'}}
    mean, err = get_psth(event_raster, trials_rc)
    psth['right_correct'] = {'vals': mean, 'err': err,
                             'linestyle': {'color': 'b'}}
    mean, err = get_psth(event_raster, trials_ri)
    psth['right_incorrect'] = {'vals': mean, 'err': err,
                               'linestyle': {'color': 'b', 'linestyle': 'dashed'}}

    raster = {}
    raster['vals'] = filter_by_trial(event_raster, trials_sorted)
    raster['dividers'] = div

    return raster, psth


def filter_correct_incorrect(trials, event_raster, event, order='trial num'):
    trials_sorted, div = find_trial_ids(trials, sort='choice', event=event, order=order)
    trials_c, _ = find_trial_ids(trials, side='all', choice='correct', event=event, order=order)
    trials_i, _ = find_trial_ids(trials, side='all', choice='incorrect', event=event, order=order)

    psth = dict()
    mean, err = get_psth(event_raster, trials_c)
    psth['correct'] = {'vals': mean, 'err': err, 'linestyle': {'color': 'r'}}
    mean, err = get_psth(event_raster, trials_i)
    psth['incorrect'] = {'vals': mean, 'err': err, 'linestyle': {'color': 'b'}}

    raster = {}
    raster['vals'] = filter_by_trial(event_raster, trials_sorted)
    raster['dividers'] = div

    return raster, psth


def filter_left_right(trials, event_raster, event, order='trial num'):
    trials_sorted, div = find_trial_ids(trials, sort='choice', event=event, order=order)
    trials_l, _ = find_trial_ids(trials, side='left', choice='all', event=event, order=order)
    trials_r, _ = find_trial_ids(trials, side='right', choice='all', event=event, order=order)

    psth = dict()
    mean, err = get_psth(event_raster, trials_l)
    psth['left'] = {'vals': mean, 'err': err, 'linestyle': {'color': 'r'}}
    mean, err = get_psth(event_raster, trials_r)
    psth['right'] = {'vals': mean, 'err': err, 'linestyle': {'color': 'b'}}

    raster = {}
    raster['vals'] = filter_by_trial(event_raster, trials_sorted)
    raster['dividers'] = div

    return raster, psth


def filter_trials(trials, event_raster, event, order='trial num', sort='choice'):
    if sort == 'choice':
        raster, psth = filter_correct_incorrect(trials, event_raster, event, order)
    elif sort == 'side':
        raster, psth = filter_left_right(trials, event_raster, event, order)
    elif sort == 'choice and side':
        raster, psth = filter_correct_incorrect_left_right(trials, event_raster, event, order)

    return raster, psth
