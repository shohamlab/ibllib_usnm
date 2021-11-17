"""
Module to work with raw voltage traces. Spike sorting pre-processing functions.
"""
from pathlib import Path

import numpy as np
import scipy.signal
from tqdm import tqdm
from joblib import Parallel, delayed, cpu_count


from ibllib.io import spikeglx
import ibllib.dsp.fourier as fdsp
from ibllib.dsp import fshift, rms
from ibllib.ephys import neuropixel


def reject_channels(x, fs, butt_kwargs=None, threshold=0.6, trx=1):
    """
    Computes the
    :param x: demultiplexed array (ntraces, nsample)
    :param fs: sampling frequency (Hz)
    :param trx: number of traces each side (1)
    :param butt kwargs (optional, None), butt_kwargs = {'N': 4, 'Wn': 0.05, 'btype': 'lp'}
    :param threshold: r value below which a channel is rejected
    :return:
    """
    ntr, ns = x.shape
    # mirror padding by taking care of not repeating first/last trace
    x = np.r_[x[1:trx + 1, :], x, x[-2 - trx:-2, :]]
    # apply butterworth
    if butt_kwargs is not None:
        sos = scipy.signal.butter(**butt_kwargs, output='sos')
        x = scipy.signal.sosfiltfilt(sos, x)
    r = np.zeros(ntr)
    for ix in np.arange(trx, ntr + trx):
        ref = np.median(x[ix - trx: ix + trx + 1, :], axis=0)
        r[ix - trx] = np.corrcoef(x[ix, :], ref)[1, 0]
    return r >= threshold, r


def agc(x, wl=.5, si=.002, epsilon=1e-8):
    """
    Automatic gain control
    w_agc, gain = agc(w, wl=.5, si=.002, epsilon=1e-8)
    such as w_agc / gain = w
    :param x: seismic array (sample last dimension)
    :param wl: window length (secs)
    :param si: sampling interval (secs)
    :param epsilon: whitening (useful mainly for synthetic data)
    :return: AGC data array, gain applied to data
    """
    ns_win = np.round(wl / si / 2) * 2 + 1
    w = np.hanning(ns_win)
    w /= np.sum(w)
    gain = np.sqrt(fdsp.convolve(x ** 2, w, mode='same'))
    gain += (np.sum(gain, axis=1) * epsilon / x.shape[-1])[:, np.newaxis]
    gain = 1 / gain
    return x * gain, gain


def fk(x, si=.002, dx=1, vbounds=None, btype='highpass', ntr_pad=0, ntr_tap=None, lagc=.5,
       collection=None, kfilt=None):
    """Frequency-wavenumber filter: filters apparent plane-waves velocity
    :param x: the input array to be filtered. dimension, the filtering is considering
    axis=0: spatial dimension, axis=1 temporal dimension. (ntraces, ns)
    :param si: sampling interval (secs)
    :param dx: spatial interval (usually meters)
    :param vbounds: velocity high pass [v1, v2], cosine taper from 0 to 1 between v1 and v2
    :param btype: {‘lowpass’, ‘highpass’}, velocity filter : defaults to highpass
    :param ntr_pad: padding will add ntr_padd mirrored traces to each side
    :param ntr_tap: taper (if None, set to ntr_pad)
    :param lagc: length of agc in seconds. If set to None or 0, no agc
    :param kfilt: optional (None) if kfilter is applied, parameters as dict (bounds are in m-1
    according to the dx parameter) kfilt = {'bounds': [0.05, 0.1], 'btype', 'highpass'}
    :param collection: vector length ntraces. Each unique value set of traces is a collection
    on which the FK filter will run separately (shot gaters, receiver gathers)
    :return:
    """
    if collection is not None:
        xout = np.zeros_like(x)
        for c in np.unique(collection):
            sel = collection == c
            xout[sel, :] = fk(x[sel, :], si=si, dx=dx, vbounds=vbounds, ntr_pad=ntr_pad,
                              ntr_tap=ntr_tap, lagc=lagc, collection=None)
        return xout

    assert vbounds
    nx, nt = x.shape

    # lateral padding left and right
    ntr_pad = int(ntr_pad)
    ntr_tap = ntr_pad if ntr_tap is None else ntr_tap
    nxp = nx + ntr_pad * 2

    # compute frequency wavenumber scales and deduce the velocity filter
    fscale = fdsp.fscale(nt, si)
    kscale = fdsp.fscale(nxp, dx)
    kscale[0] = 1e-6
    v = fscale[np.newaxis, :] / kscale[:, np.newaxis]
    if btype.lower() in ['highpass', 'hp']:
        fk_att = fdsp.fcn_cosine(vbounds)(np.abs(v))
    elif btype.lower() in ['lowpass', 'lp']:
        fk_att = (1 - fdsp.fcn_cosine(vbounds)(np.abs(v)))

    # if a k-filter is also provided, apply it
    if kfilt is not None:
        katt = fdsp._freq_vector(np.abs(kscale), kfilt['bounds'], typ=kfilt['btype'])
        fk_att *= katt[:, np.newaxis]

    # import matplotlib.pyplot as plt
    # plt.imshow(np.fft.fftshift(np.abs(v), axes=0).T, aspect='auto', vmin=0, vmax=1e5,
    #            extent=[np.min(kscale), np.max(kscale), 0, np.max(fscale) * 2])
    # plt.imshow(np.fft.fftshift(np.abs(fk_att), axes=0).T, aspect='auto', vmin=0, vmax=1,
    #            extent=[np.min(kscale), np.max(kscale), 0, np.max(fscale) * 2])

    # apply the attenuation in fk-domain
    if not lagc:
        xf = np.copy(x)
        gain = 1
    else:
        xf, gain = agc(x, wl=lagc, si=si)
    if ntr_pad > 0:
        # pad the array with a mirrored version of itself and apply a cosine taper
        xf = np.r_[np.flipud(xf[:ntr_pad]), xf, np.flipud(xf[-ntr_pad:])]
    if ntr_tap > 0:
        taper = fdsp.fcn_cosine([0, ntr_tap])(np.arange(nxp))  # taper up
        taper *= 1 - fdsp.fcn_cosine([nxp - ntr_tap, nxp])(np.arange(nxp))   # taper down
        xf = xf * taper[:, np.newaxis]
    xf = np.real(np.fft.ifft2(fk_att * np.fft.fft2(xf)))

    if ntr_pad > 0:
        xf = xf[ntr_pad:-ntr_pad, :]
    return xf / gain


def kfilt(x, collection=None, ntr_pad=0, ntr_tap=None, lagc=300, butter_kwargs=None):
    """
    Applies a butterworth filter on the 0-axis with tapering / padding
    :param x: the input array to be filtered. dimension, the filtering is considering
    axis=0: spatial dimension, axis=1 temporal dimension. (ntraces, ns)
    :param collection:
    :param ntr_pad: traces added to each side (mirrored)
    :param ntr_tap: n traces for apodizatin on each side
    :param lagc: window size for time domain automatic gain control (no agc otherwise)
    :param butter_kwargs: filtering parameters: defaults: {'N': 3, 'Wn': 0.1, 'btype': 'highpass'}
    :return:
    """
    if butter_kwargs is None:
        butter_kwargs = {'N': 3, 'Wn': 0.1, 'btype': 'highpass'}
    if collection is not None:
        xout = np.zeros_like(x)
        for c in np.unique(collection):
            sel = collection == c
            xout[sel, :] = kfilt(x=x[sel, :], ntr_pad=0, ntr_tap=None, collection=None,
                                 butter_kwargs=butter_kwargs)
        return xout
    nx, nt = x.shape

    # lateral padding left and right
    ntr_pad = int(ntr_pad)
    ntr_tap = ntr_pad if ntr_tap is None else ntr_tap
    nxp = nx + ntr_pad * 2

    # apply agc and keep the gain in handy
    if not lagc:
        xf = np.copy(x)
        gain = 1
    else:
        xf, gain = agc(x, wl=lagc, si=1.0)
    if ntr_pad > 0:
        # pad the array with a mirrored version of itself and apply a cosine taper
        xf = np.r_[np.flipud(xf[:ntr_pad]), xf, np.flipud(xf[-ntr_pad:])]
    if ntr_tap > 0:
        taper = fdsp.fcn_cosine([0, ntr_tap])(np.arange(nxp))  # taper up
        taper *= 1 - fdsp.fcn_cosine([nxp - ntr_tap, nxp])(np.arange(nxp))   # taper down
        xf = xf * taper[:, np.newaxis]
    sos = scipy.signal.butter(**butter_kwargs, output='sos')
    xf = scipy.signal.sosfiltfilt(sos, xf, axis=0)

    if ntr_pad > 0:
        xf = xf[ntr_pad:-ntr_pad, :]
    return xf / gain


def destripe(x, fs, tr_sel=None, neuropixel_version=1, butter_kwargs=None, k_kwargs=None):
    """Super Car (super slow also...) - far from being set in stone but a good workflow example
    :param x: demultiplexed array (ntraces, nsample)
    :param fs: sampling frequency
    :param neuropixel_version (optional): 1 or 2. Useful for the ADC shift correction. If None,
     no correction is applied
    :param tr_sel: index array for the first axis of x indicating the selected traces.
     On a full workflow, one should scan sparingly the full file to get a robust estimate of the
     selection. If None, and estimation is done using only the current batch is provided for
     convenience but should be avoided in production.
    :param butter_kwargs: (optional, None) butterworth params, see the code for the defaults dict
    :param k_kwargs: (optional, None) K-filter params, see the code for the defaults dict
    :return: x, filtered array
    """
    if butter_kwargs is None:
        butter_kwargs = {'N': 3, 'Wn': 300 / fs / 2, 'btype': 'highpass'}
    if k_kwargs is None:
        k_kwargs = {'ntr_pad': 60, 'ntr_tap': 0, 'lagc': 3000,
                    'butter_kwargs': {'N': 3, 'Wn': 0.01, 'btype': 'highpass'}}
    h = neuropixel.trace_header(version=neuropixel_version)
    # butterworth
    sos = scipy.signal.butter(**butter_kwargs, output='sos')
    x = scipy.signal.sosfiltfilt(sos, x)
    # apply ADC shift
    if neuropixel_version is not None:
        sample_shift = h['sample_shift'] if (30000 / fs) < 10 else h['sample_shift'] * fs / 30000
        x = fshift(x, sample_shift, axis=1)
    # apply spatial filter on good channel selection only
    x_ = kfilt(x, **k_kwargs)
    return x_


def decompress_destripe_cbin(sr_file, output_file=None, h=None, wrot=None, append=False, nc_out=None,
                             dtype=np.int16, ns2add=0, nbatch=None, nprocesses=None, compute_rms=True):
    """
    From a spikeglx Reader object, decompresses and apply ADC.
    Saves output as a flat binary file in int16
    Production version with optimized FFTs - requires pyfftw
    :param sr: seismic reader object (spikeglx.Reader)
    :param output_file: (optional, defaults to .bin extension of the compressed bin file)
    :param h: (optional)
    :param wrot: (optional) whitening matrix [nc x nc] or amplitude scalar to apply to the output
    :param append: (optional, False) for chronic recordings, append to end of file
    :param nc_out: (optional, True) saves non selected channels (synchronisation trace) in output
    :param dtype: (optional, np.int16) output sample format
    :param ns2add: (optional) for kilosort, adds padding samples at the end of the file so the total
    number of samples is a multiple of the batchsize
    :param nbatch: (optional) batch size
    :param nprocesses: (optional) number of parallel processes to run, defaults to number or processes detected with joblib
    :return:
    """
    import pyfftw

    SAMPLES_TAPER = 128
    NBATCH = nbatch or 65536
    # handles input parameters
    assert isinstance(sr_file, str) or isinstance(sr_file, Path)
    sr = spikeglx.Reader(sr_file, open=True)
    butter_kwargs = {'N': 3, 'Wn': 300 / sr.fs / 2, 'btype': 'highpass'}
    k_kwargs = {'ntr_pad': 60, 'ntr_tap': 0, 'lagc': 3000,
                'butter_kwargs': {'N': 3, 'Wn': 0.01, 'btype': 'highpass'}}
    h = neuropixel.trace_header(version=1) if h is None else h
    output_file = sr.file_bin.with_suffix('.bin') if output_file is None else output_file
    assert output_file != sr.file_bin
    taper = np.r_[0, scipy.signal.windows.cosine((SAMPLES_TAPER - 1) * 2), 0]
    # create the FFT stencils
    ncv = h['x'].size  # number of channels
    nc_out = nc_out or sr.nc
    # compute LP filter coefficients
    sos = scipy.signal.butter(**butter_kwargs, output='sos')
    nbytes = dtype(1).nbytes
    nprocesses = nprocesses or int(cpu_count() - cpu_count() / 4)

    win = pyfftw.empty_aligned((ncv, NBATCH), dtype='float32')
    WIN = pyfftw.empty_aligned((ncv, int(NBATCH / 2 + 1)), dtype='complex64')
    fft_object = pyfftw.FFTW(win, WIN, axes=(1,), direction='FFTW_FORWARD', threads=4)
    dephas = np.zeros((ncv, NBATCH), dtype=np.float32)
    dephas[:, 1] = 1.
    DEPHAS = np.exp(1j * np.angle(fft_object(dephas)) * h['sample_shift'][:, np.newaxis])

    ap_rms_file = output_file.parent.joinpath('ap_rms.bin')
    rms_nbytes = np.float32(1).nbytes

    if append:
        # need to find the end of the file and the offset
        offset = Path(output_file).stat().st_size
        rms_offset = Path(ap_rms_file).stat().st_size
    else:
        offset = 0
        rms_offset = 0
        open(output_file, 'wb').close()
        open(ap_rms_file, 'wb').close()

    # chunks to split the file into, dependent on number of parallel processes
    CHUNK_SIZE = int(sr.ns / nprocesses)

    def my_function(i_chunk, n_chunk):
        _sr = spikeglx.Reader(sr_file)

        n_batch = int(np.ceil(i_chunk * CHUNK_SIZE / NBATCH))
        first_s = (NBATCH - SAMPLES_TAPER * 2) * n_batch

        # Find the maximum sample for each chunk
        max_s = _sr.ns if i_chunk == n_chunk - 1 else (i_chunk + 1) * CHUNK_SIZE
        pbar = tqdm(total=CHUNK_SIZE / _sr.fs)

        win = pyfftw.empty_aligned((ncv, NBATCH), dtype='float32')
        WIN = pyfftw.empty_aligned((ncv, int(NBATCH / 2 + 1)), dtype='complex64')
        fft_object = pyfftw.FFTW(win, WIN, axes=(1,), direction='FFTW_FORWARD', threads=4)
        ifft_object = pyfftw.FFTW(WIN, win, axes=(1,), direction='FFTW_BACKWARD', threads=4)

        with open(output_file, 'r+b') as fid, open(ap_rms_file, 'r+b') as aid:
            if i_chunk == 0:
                fid.seek(offset)
                aid.seek(rms_offset)
            else:
                fid.seek(offset + ((first_s + SAMPLES_TAPER) * nc_out * nbytes))
                aid.seek(rms_offset + (i_chunk * nc_out * rms_nbytes))

            while True:
                last_s = np.minimum(NBATCH + first_s, _sr.ns)

                # Apply tapers
                ap_rms = rms(_sr[first_s:last_s, :ncv] - np.mean(_sr[first_s:last_s, :ncv], axis=0))
                ap_rms.astype(np.float32).tofile(aid)


                chunk = _sr[first_s:last_s, :ncv].T
                chunk[:, :SAMPLES_TAPER] *= taper[:SAMPLES_TAPER]
                chunk[:, -SAMPLES_TAPER:] *= taper[SAMPLES_TAPER:]

                # Apply filters
                chunk = scipy.signal.sosfiltfilt(sos, chunk)

                # Find the indices to save
                ind2save = [SAMPLES_TAPER, NBATCH - SAMPLES_TAPER]

                if last_s == _sr.ns:
                    # for the last batch just use the normal fft as the stencil doesn't fit
                    chunk = fshift(chunk, s=h['sample_shift'])
                    ind2save[1] = NBATCH
                else:
                    # apply precomputed fshift of the proper length
                    chunk = ifft_object(fft_object(chunk) * DEPHAS)

                if first_s == 0:
                    # for the first batch save the start with taper applied
                    ind2save[0] = 0

                # add back sync trace and save
                chunk = kfilt(chunk, **k_kwargs)
                chunk = np.r_[chunk, _sr[first_s:last_s, ncv:].T].T
                intnorm = 1 / _sr.channel_conversion_sample2v['ap'] if dtype == np.int16 else 1.
                chunk = chunk[slice(*ind2save), :] * intnorm

                if wrot is not None:
                    chunk[:, :ncv] = np.dot(chunk[:, :ncv], wrot)

                chunk[:, :nc_out].astype(np.int16).tofile(fid)
                first_s += NBATCH - SAMPLES_TAPER * 2
                pbar.update(NBATCH / _sr.fs)
                if last_s >= max_s:
                    if last_s == _sr.ns:
                        if ns2add > 0:
                            np.tile(chunk[-1, :nc_out].astype(dtype), (ns2add, 1)).tofile(fid)
                    break
        pbar.close()

    _ = Parallel(n_jobs=nprocesses)(delayed(my_function)(i, nprocesses) for i in range(nprocesses))
    sr.close()


def rcoeff(x, y):
    """
    Computes pairwise Person correlation coefficients for matrices.
    That is for 2 matrices the same size, computes the row to row coefficients and outputs
    a vector corresponding to the number of rows of the first matrix
    If the second array is a vector then computes the correlation coefficient for all rows
    :param x: np array [nc, ns]
    :param y: np array [nc, ns] or [ns]
    :return: r [nc]
    """
    def normalize(z):
        mean = np.mean(z, axis=-1)
        return z - mean if mean.size == 1 else z - mean[:, np.newaxis]
    xnorm = normalize(x)
    ynorm = normalize(y)
    rcor = np.sum(xnorm * ynorm, axis=-1) / np.sqrt(np.sum(np.square(xnorm), axis=-1) * np.sum(np.square(ynorm), axis=-1))
    return rcor


def detect_bad_channels(raw, fs, similarity_threshold=(-0.5, 1), psd_hf_threshold=0.02):
    """
    Bad channels detection for Neuropixel probes
    Labels channels
     0: all clear
     1: dead low coherence / amplitude
     2: noisy
     3: outside of the brain
    :param raw: [nc, ns]
    :param fs: sampling frequency
    :param similarity_threshold:
    :param psd_hf_threshold:
    :return: labels (numpy vector [nc]), xfeats: dictionary of features [nc]
    """

    def rneighbours(raw, n=1):  # noqa
        """
        Computes Pearson correlation with the sum of neighbouring traces
        :param raw: nc, ns
        :param n:
        :return:
        """
        nc = raw.shape[0]
        mixer = np.triu(np.ones((nc, nc)), 1) - np.triu(np.ones((nc, nc)), 1 + n)
        mixer += np.tril(np.ones((nc, nc)), -1) - np.tril(np.ones((nc, nc)), - n - 1)
        r = rcoeff(raw, np.matmul(raw.T, mixer).T)
        r[np.isnan(r)] = 0
        return r

    def detrend(x, nmed):
        ntap = int(np.ceil(nmed / 2))
        xf = np.r_[np.zeros(ntap) + x[0], x, np.zeros(ntap) + x[-1]]
        # assert np.all(xcorf[ntap:-ntap] == xcor)
        xf = scipy.signal.medfilt(xf, nmed)[ntap:-ntap]
        return x - xf

    def channels_similarity(raw, nmed=0):
        """
        Computes the similarity based on zero-lag crosscorrelation of each channel with the median
        trace referencing
        :param raw: [nc, ns]
        :param nmed:
        :return:
        """
        def fxcor(x, y):
            return scipy.fft.irfft(scipy.fft.rfft(x) * np.conj(scipy.fft.rfft(y)), n=raw.shape[-1])

        def nxcor(x, ref):
            ref = ref - np.mean(ref)
            apeak = fxcor(ref, ref)[0]
            x = x - np.mean(x, axis=-1)[:, np.newaxis]
            return fxcor(x, ref)[:, 0] / apeak

        ref = np.median(raw, axis=0)
        xcor = nxcor(raw, ref)

        if nmed > 0:
            xcor = detrend(xcor, nmed) + 1
        return xcor

    nc, _ = raw.shape
    raw = raw - np.mean(raw, axis=-1)[:, np.newaxis]  # removes DC offset
    xcor = channels_similarity(raw)
    fscale, psd = scipy.signal.welch(raw * 1e6, fs=fs)  # units; uV ** 2 / Hz

    sos_hp = scipy.signal.butter(**{'N': 3, 'Wn': 1000 / fs / 2, 'btype': 'highpass'}, output='sos')
    hf = scipy.signal.sosfiltfilt(sos_hp, raw)
    xcorf = channels_similarity(hf)

    xfeats = ({
        'ind': np.arange(nc),
        'rms_raw': rms(raw),  # very similar to the rms avfter butterworth filter
        'xcor_hf': detrend(xcor, 11),
        'xcor_lf': xcorf - detrend(xcorf, 11) - 1,
        'psd_hf': np.mean(psd[:, fscale > 12000], axis=-1),
    })

    # make recommendation
    ichannels = np.zeros(nc)
    idead = np.where(similarity_threshold[0] > xfeats['xcor_hf'])[0]
    inoisy = np.where(np.logical_or(xfeats['psd_hf'] > psd_hf_threshold, xfeats['xcor_hf'] > similarity_threshold[1]))[0]
    # the channels outside of the brains are the contiguous channels below the threshold on the trend coherency
    ioutside = np.where(xfeats['xcor_lf'] < -0.75)[0]
    if ioutside.size > 0 and ioutside[-1] == (nc - 1):
        a = np.cumsum(np.r_[0, np.diff(ioutside) - 1])
        ioutside = ioutside[a == np.max(a)]
        ichannels[ioutside] = 3

    # indices
    ichannels[idead] = 1
    ichannels[inoisy] = 2
    return ichannels, xfeats
