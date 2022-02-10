import glob
import time
import numpy as np
from scipy.io import wavfile
import wave

import contextlib
import subprocess
import soundfile as sf
from tqdm import tqdm
from pathlib import Path
import os

def get_duration_file(fn_audio):
    """Getting duration information of audio files

    Args:
        fn_audio (str): path to audio file

    Returns:
        [type]: [description]
    """
    with contextlib.closing(wave.open(str(fn_audio),'r')) as f:
        frames = f.getnframes()
        rate = f.getframerate()
        duration = frames / float(rate)
    return duration

def get_infor_file(fn_audio):
    ob =  sf.SoundFile(fn_audio)
    return ob.subtype, ob.samplerate, ob.channels


def get_amplitute_file(path):
    sr, data = wavfile.read(path)
#     bit_depth = int(get_infor_file(path)[0].split('_')[-1])
    bit_depth = 16
    db = 20 * np.log10(max(abs(data))/(2**(bit_depth - 1) - 1))
    return sr, min(data), max(data), db

def get_duration_folder(folder):
    total_length = 0
    for audio in glob.glob(f"{folder}/*.wav"):
        try:
            total_length += get_duration_file(audio)
        except:
            print("error in ",audio)
    return total_length


def get_size_file(fname):
    return Path(fname).stat().st_size

def get_size_folder(folder):
    return sum([float(get_size_file(f)) for f in glob.glob(f"{folder}/*")])

def get_dataset_general_infor(root="dataset/train"):
    root = Path(root)
    # get numbr of file
    audio_folder_num = {}
    for audio_folder in tqdm(root.iterdir(), desc="getting number of files"):
        audio_folder_num[audio_folder.name] = len(os.listdir(audio_folder))

    # get duration of files
    audio_folder_duration = {}
    for audio_folder in tqdm(root.iterdir(), desc="getting duration of files"):
        audio_folder_duration[audio_folder.name] = list([get_duration_file(audio_file) for audio_file in audio_folder.iterdir()])

    # get size of files
    audio_folder_size = {}
    for audio_folder in tqdm(root.iterdir(), desc="getting size of files"):
        audio_folder_size[audio_folder.name] = list([get_size_file(audio_file) for audio_file in audio_folder.iterdir()])
    
    # get amplitue of file take long time :v
#     audio_folder_amplitute = {}
#     for audio_folder in tqdm(root.iterdir(), desc="getting peak amplitude of files"):
#         audio_folder_amplitute[audio_folder.name] = list([get_amplitute_file(audio_file)[-1] for audio_file in audio_folder.iterdir()])
    
    return audio_folder_num, audio_folder_duration, audio_folder_size


def get_audio_ffmpeg_astats(filename):
    """Get stats information of audio 
    Display time domain statistical information about the audio channels. Statistics are calculated and displayed for each audio channel and, where applicable, an overall figure is also given.

    It accepts the following option:

    length: Short window length in seconds, used for peak and trough RMS measurement. Default is 0.05 (50 milliseconds). Allowed range is [0 - 10].

    metadata: Set metadata injection. All the metadata keys are prefixed with lavfi.astats.X, where X is channel number starting from 1 or string Overall. Default is disabled.
    Available keys for each channel are: DC_offset Min_level Max_level Min_difference Max_difference Mean_difference RMS_difference Peak_level RMS_peak RMS_trough Crest_factor Flat_factor Peak_count Noise_floor Noise_floor_count Entropy Bit_depth Dynamic_range Zero_crossings Zero_crossings_rate Number_of_NaNs Number_of_Infs Number_of_denormals
    and for Overall: DC_offset Min_level Max_level Min_difference Max_difference Mean_difference RMS_difference Peak_level RMS_level RMS_peak RMS_trough Flat_factor Peak_count Noise_floor Noise_floor_count Entropy Bit_depth Number_of_samples Number_of_NaNs Number_of_Infs Number_of_denormals
    For example full key look like this lavfi.astats.1.DC_offset or this lavfi.astats.Overall.Peak_count.

    For description what each key means read below.
    - reset: Set the number of frames over which cumulative stats are calculated before being reset Default is disabled.
    - measure_perchannel: Select the parameters which are measured per channel. The metadata keys can be used as flags, default is all which measures everything. none disables all per channel measurement.
    - measure_overall: Select the parameters which are measured overall. The metadata keys can be used as flags, default is all which measures everything. none disables all overall measurement.
    A description of each shown parameter follows:

    - DC offset: Mean amplitude displacement from zero.

    - Min level: Minimal sample level.

    - Max level: Maximal sample level.

    - Min difference: Minimal difference between two consecutive samples.

    - Max difference: Maximal difference between two consecutive samples.

    - Mean difference: Mean difference between two consecutive samples. The average of each difference between two consecutive samples.

    - RMS difference: Root Mean Square difference between two consecutive samples.

    - Peak level dB & RMS level dB: Standard peak and RMS level measured in dBFS.

    - RMS peak dB & RMS trough dB: Peak and trough values for RMS level measured over a short window.

    - Crest factor: Standard ratio of peak to RMS level (note: not in dB).

    - Flat factor: Flatness (i.e. consecutive samples with the same value) of the signal at its peak levels (i.e. either Min level or Max level).

    - Peak count: Number of occasions (not the number of samples) that the signal attained either Min level or Max level.

    - Noise floor dB: Minimum local peak measured in dBFS over a short window.

    - Noise floor count: Number of occasions (not the number of samples) that the signal attained Noise floor.

    - Entropy: Entropy measured across whole audio. Entropy of value near 1.0 is typically measured for white noise.

    - Bit depth: Overall bit depth of audio. Number of bits used for each sample.

    - Dynamic range: Measured dynamic range of audio in dB.

    - Zero crossings: Number of points where the waveform crosses the zero level axis.

    - Zero crossings rate: Rate of Zero crossings and number of audio samples

    Args:
        filename ([str]): path to audio file

    Returns:
        dict: dictionary of information
    """
    cmd = ['ffmpeg', '-i', filename, '-map', '0:a', '-af', 'astats', '-f', 'null', '-']
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr
    output_lines = [line.strip() for line in out.decode('utf-8').split('\n')]
    
    
    # filter
    header = ['Duration', 'Size', 'Min level', 'Max level', 
              'Min difference', 'Max difference', 'Mean difference', 'RMS difference', 
              'Peak level dB', 'RMS level dB',   'RMS peak dB', 'RMS trough dB', 
              'Crest factor', 'Flat factor', 'Peak count',
              'Noise floor dB', 'Noise floor count', 'Bit depth', 'Dynamic range', 
              'Zero crossings', 'Zero crossings rate']
    details = {}
    condition = lambda x: 'Parsed_astats_0' in x
    filtered_lines = list(filter(condition, output_lines))

    for line in filtered_lines:
        detail = line.replace(f"[{line.split('[')[-1].split(']')[0]}]", '').strip().split(':')
        if detail[0] == 'Overall':
            continue
        details[detail[0]] = detail[1]
    for k in header:
        if k not in details:
            details[k] = None
    
    
    details['Duration'] = get_duration_file(filename)
    details['Size'] = get_size_file(filename)
    
    return details
