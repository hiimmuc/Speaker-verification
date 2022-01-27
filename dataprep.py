# run on linux only
import argparse
import glob
import hashlib
import os
import random
import shutil
import subprocess
import tarfile
import time
from pathlib import Path
from zipfile import ZipFile

import librosa
import numpy as np
import scipy
import soundfile as sf
from scipy.io import wavfile

from tqdm.auto import tqdm

from utils import *
import wave
import contextlib
import csv

def get_audio_path(folder):
    """
    Get the audio path for a given folder

    Args:
        folder ([type]): [description]

    Returns:
        list: [description]
    """
    return glob.glob(os.path.join(folder, '*.wav'))


def md5(fname):
    """
    MD5SUM
    """
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def download(args, lines):
    """
    Download with wget
    """
    for line in lines:
        url = line.split()[0]
        md5gt = line.split()[1]
        outfile = url.split('/')[-1]

        # Download files
        out = subprocess.call('wget %s -O %s/%s' %
                              (url, args.save_path, outfile),
                              shell=True)
        if out != 0:
            raise ValueError(
                'Download failed %s. If download fails repeatedly, use alternate URL on the VoxCeleb website.'
                % url)

        # Check MD5
        md5ck = md5('%s/%s' % (args.save_path, outfile))
        if md5ck == md5gt:
            print('Checksum successful %s.' % outfile)
        else:
            raise Warning('Checksum failed %s.' % outfile)


def full_extract(args, fname):
    """
    Extract zip files
    """
    print('Extracting %s' % fname)
    if fname.endswith(".tar.gz"):
        with tarfile.open(fname, "r:gz") as tar:
            tar.extractall(args.save_path)
    elif fname.endswith(".zip"):
        with ZipFile(fname, 'r') as zf:
            zf.extractall(args.save_path)


def part_extract(args, fname, target):
    """
    Partially extract zip files
    """
    print('Extracting %s' % fname)
    with ZipFile(fname, 'r') as zf:
        for infile in zf.namelist():
            if any([infile.startswith(x) for x in target]):
                zf.extract(infile, args.save_path)


def split_musan(args):
    """
    Split MUSAN for faster random access
    """

    files = glob.glob('%s/musan/*/*/*.wav' % args.augment_path)

    audlen = 16000 * 5
    audstr = 16000 * 3

    for idx, file in enumerate(files):
        fs, aud = wavfile.read(file)
        writedir = os.path.splitext(file.replace('/musan/',
                                                 '/musan_split/'))[0]
        os.makedirs(writedir)
        for st in range(0, len(aud) - audlen, audstr):
            wavfile.write(writedir + '/%05d.wav' % (st / fs), fs,
                          aud[st:st + audlen])

        print(idx, file)


def prepare_augmentation(args):
    """
    Check wether the augmentation dataset is already downloaded

    Args:
        args ([type]): [description]
    """
    # TODO: check if the augmentation dataset is already downloaded -> extract only
    if not os.path.exists(args.augment_path):
        print('Downloading augmentation dataset...')
        with open('dataset/augment.txt', 'r') as f:
            augfiles = f.readlines()
        download(args, augfiles)

        part_extract(args, os.path.join(args.augment_path, 'rirs_noises.zip'), [
            'RIRS_NOISES/simulated_rirs/mediumroom',
            'RIRS_NOISES/simulated_rirs/smallroom'
        ])

        full_extract(args, os.path.join(args.augment_path, 'musan.tar.gz'))

        split_musan(args)
    else:
        print('Augmentation dataset already exists in', args.augment_path)

    if not os.path.exists(args.raw_dataset):
        raise "Raw dataset is empty"


def augmentation(args, audio_paths, mode='train', max_frames=400, step_save=500):
    """
    Perfrom augmentation on the raw dataset
    """

    prepare_augmentation(args)  # check if augumentation data is ready

    aug_rate = args.aug_rate
    musan_path = Path(args.augment_path, 'musan_split')
    rir_path = Path(args.augment_path, 'RIRS_NOISES/simulated_rirs')
    print('Start augmenting data with', musan_path, 'and', rir_path)

    if mode == 'train':
        print('Augment Full')
        num_aug = len(audio_paths)
        augment_audio_paths = audio_paths
    elif mode == 'test':
        num_aug = int(aug_rate * len(audio_paths))
        random_indices = random.sample(range(len(audio_paths)), num_aug)
        augment_audio_paths = [audio_paths[i] for i in random_indices]
    else:
        raise ValueError('mode should be train or test')

    print('Number of augmented data: {}/{}'.format(num_aug, len(audio_paths)))

    augment_engine = AugmentWAV(musan_path, rir_path, max_frames)

    list_audio = []

    for idx, fpath in enumerate(tqdm(augment_audio_paths, unit='files', desc=f"Augmented process")):
        audio, sr = loadWAV(fpath, max_frames=max_frames,
                            evalmode=False, sr=16000)
        if mode == 'test':
            aug_type = random.randint(1, 4)

            if aug_type == 1:
                audio = augment_engine.reverberate(audio)
            elif aug_type == 2:
                audio = augment_engine.additive_noise('music', audio)
            elif aug_type == 3:
                audio = augment_engine.additive_noise('speech', audio)
            elif aug_type == 4:
                audio = augment_engine.additive_noise('noise', audio)

            list_audio.append([audio, aug_type])
            s = 1
        else:
            aug_audio1 = augment_engine.reverberate(audio)
            aug_audio2 = augment_engine.additive_noise('music', audio)
            aug_audio3 = augment_engine.additive_noise('speech', audio)
            aug_audio4 = augment_engine.additive_noise('noise', audio)
            aug_audio = [aug_audio1, aug_audio2, aug_audio3, aug_audio4]

            for i, audio_ in enumerate(aug_audio):
                list_audio.append([audio_, i + 1])
            s = 4

        roots = [os.path.split(fpath)[0] for fpath in augment_audio_paths]
        # change_path to test folder
        if mode == 'test':
            roots = [path.replace('wavs', 'test') for path in roots]
        audio_names = [os.path.split(fpath)[1]
                       for fpath in augment_audio_paths]

        # save list of augment audio each step = save_step (default 500)
        if (idx + 1) % step_save == 0 or (idx == len(augment_audio_paths) - 1):
            ii = ((idx + 1) // step_save - 1) * \
                step_save if idx + 1 >= step_save else 0

            for i, (audio, aug_t) in enumerate(tqdm(list_audio, unit='file', desc=f'Save augmented files {ii} -> {idx}')):
                save_path = os.path.join(
                    roots[i//s + ii], f"{audio_names[i//s + ii].replace('.wav', '')}_augmented_{aug_t}.wav")

                if os.path.exists(save_path):
                    os.remove(save_path)
                else:
                    os.makedirs(os.path.split(save_path)[0], exist_ok=True)
                    
                audio = audio.T
                sf.write(str(save_path), audio, sr)
            list_audio = []  # refresh list to avoid memory overload
    print('Done!')


def clean_dump_files(args):
    """check whether the structure is not correct"""
    data_files = []
    raw_path = args.raw_dataset

    with open(os.path.join(args.save_dir, 'data_folders.txt'), 'r') as f:
        data_files = f.readlines()
        data_files = list(
            map(lambda x: x.replace('\n', ''), data_files))

    for path in tqdm(data_files):
        for invalid in os.listdir(path):
            path_invalid = os.path.join(path, invalid)
            if os.path.isdir(path_invalid):
                print(path_invalid, end=' ')
                if len(os.listdir(path_invalid)) == 0:
                    print('empty', end='\n')
                    os.rmdir(path_invalid)  # remove empty folder
                else:
                    # move file to parent folder
                    if os.path.isdir(os.path.join(raw_path, invalid)):
                        for audio in os.listdir(path_invalid):
                            if audio not in os.listdir(os.path.join(raw_path, invalid)):
                                audio = audio.replace('.wav', '') + '_add_'+'.wav'
                                shutil.move(src=os.path.join(path_invalid, audio),
                                            dst=os.path.join(os.path.join(raw_path, invalid), audio))
                        shutil.rmtree(path_invalid)

def read_blacklist(id, duration_limit=1.0, dB_limit=-16, error_limit=0, noise_limit=-15, details_dir="dataset/train_details_full/"):
    '''
    header = ['File name', 'Duration', 'Size(MB)', 'Min level', 'Max level', 
              'Min difference', 'Max difference', 'Mean difference', 'RMS difference', 
              'Peak level dB', 'RMS level dB',   'RMS peak dB', 'RMS trough dB', 
              'Crest factor', 'Flat factor', 'Peak count',
              'Noise floor dB', 'Noise floor count', 'Bit depth', 'Dynamic range', 
              'Zero crossings', 'Zero crossings rate', 'Error rate', 'Full path']
    '''
    blacklist = []
    readfile = str(Path(details_dir, f"{id}.csv"))
    if os.path.exists(readfile):
        with open(readfile, 'r', newline='') as rf:
            spamreader = csv.reader(rf, delimiter=',')
            next(spamreader, None)
            for row in spamreader:
                short_length = (float(row[1]) < duration_limit)
                low_amplitude = (float(row[9]) < dB_limit)
                high_err = (float(row[-2]) >= error_limit)
                high_noise = (float(row[16]) > noise_limit)
                if short_length or low_amplitude or high_err or high_noise:
                    blacklist.append(Path(row[-1]))
        return list(set(blacklist))
    else:
        return None
                        
class DataGenerator():
    def __init__(self, args, **kwargs):
        self.args = args
        self.data_paths = self.get_data_paths()
        if self.args.convert:
            clean_dump_files(self.args)

    def get_data_paths(self):
        raw_data_dir = self.args.raw_dataset

        data_paths = []
        for fdir in os.listdir(raw_data_dir):
            data_paths.extend(
                glob.glob(os.path.join(raw_data_dir, f'{fdir}/*.wav')))

#         with open(os.path.join(self.args.save_dir, 'data.txt'), 'w') as f:
#             for path in data_paths:
#                 f.write(f'{path}\n')
        data_folder = list(set([os.path.split(path)[0]
                           for path in data_paths]))

#         with open(os.path.join(self.args.save_dir, 'data_folders.txt'), 'w') as f:
#             for path in data_folder:
#                 f.write(f'{path}\n')
        non_augment_path = list(
            filter(lambda x: 'augment' not in str(x), data_paths))
        augment_data_paths = list(filter(lambda x: 'augment' in str(x), data_paths))
        return non_augment_path, augment_data_paths

    def convert(self):
        # convert data to one form 16000Hz, only works on Linux
        spk_files = list(Path(self.args.raw_dataset).glob('*/'))
        spk_files.sort()
        if self.args.num_spks > 0:
            spk_files = spk_files[:self.args.num_spks]
        
        files = []
        for spk in spk_files:
            files += list(Path(spk).glob('*.wav'))
            
        print(f"Converting process, Total: {len(files)}/{len(spk_files)}")
        
        for fpath in tqdm(files):
            fpath = str(fpath).replace('(', '\(')
            fpath = str(Path(fpath.replace(')', '\)')))
            outpath = str(Path(fpath[:-4] + '_conv' + fpath[-4:]))
            out = subprocess.call(
                'ffmpeg -y -i %s -ac 1 -vn -acodec pcm_s16le -ar 16000 %s >/dev/null 2>/dev/null'
                % (fpath, outpath),
                shell=True)
            if out != 0:
                raise ValueError('Conversion failed %s.' % fpath)
            subprocess.call('rm %s' % (fpath), shell=True)
            subprocess.call('mv %s %s' % (outpath, fpath), shell=True)
        print('Done!')

    def generate_lists(self):
        """
        Generate train test lists for zalo data
        """
        no_spks = 0
        root = Path(self.args.raw_dataset)
        train_writer = open(Path(root.parent, 'train_def_cb_anbn.txt'), 'w')
        val_writer = open(Path(root.parent, 'val_def_cb_anbn.txt'), 'w')
        classpaths = [d for d in root.iterdir() if d.is_dir()]
        classpaths.sort()
        
        if 0 < self.args.num_spks < len(classpaths) + 1:
            classpaths = classpaths[:self.args.num_spks]
        elif self.args.num_spks == -1:
            pass
        else:
            raise "Invalid number of speakers"

        print('Generate dataset metadata files, total:', len(classpaths))
        val_filepaths_list = []
        for classpath in tqdm(classpaths, desc="Processing:..."):
            filepaths = list(classpath.glob('*.wav'))

            # check duration, volumn
            blist = read_blacklist(str(Path(classpath).name), 
                                   duration_limit=1.0, 
                                   dB_limit=-10, 
                                   error_limit=0.5, 
                                   noise_limit=-10,
                                   details_dir=self.args.details_dir)
            if not blist:
                continue
                
            filepaths = list(set(filepaths).difference(set(blist)))

            # check duration, sr
            filepaths = check_valid_audio(filepaths, 1.0, 8000)

            # checknumber of files
            if len(filepaths) < 10:
                continue
            elif len(filepaths) >= 40:
                filepaths = filepaths[:40]
            no_spks += 1
            
            random.shuffle(filepaths)
            
            val_num = 3  # 3 utterances per speaker for val
            
            if self.args.split_ratio > 0:
                val_num = int(self.args.split_ratio * len(filepaths))

            val_filepaths = random.sample(filepaths, val_num)
            
            train_filepaths = list(set(filepaths).difference(set(val_filepaths))) if self.args.split_ratio > 0 else filepaths
        
            for train_filepath in train_filepaths:
                label = str(train_filepath.parent.stem.split('-')[0])
                train_writer.write(label + ' ' + str(train_filepath) + '\n')
            val_filepaths_list.append(val_filepaths)

        for val_filepaths in val_filepaths_list:
            for i in range(len(val_filepaths) - 1):
                for j in range(i + 1, len(val_filepaths)):
                    label = '1'
                    val_writer.write(label + ' ' + str(val_filepaths[i]) + ' ' +
                                     str(val_filepaths[j]) + '\n')
                    label = '0'
                    while True:
                        x = random.randint(0, len(val_filepaths_list) - 1)
                        if not val_filepaths_list[x]:
                            continue
                        if val_filepaths_list[x][0].parent.stem != val_filepaths[
                                i].parent.stem:
                            break
                    y = random.randint(0, len(val_filepaths_list[x]) - 1)
                    val_writer.write(label + ' ' + str(val_filepaths[i]) + ' ' +
                                     str(val_filepaths_list[x][y]) + '\n')
        print("Valid speakers:", no_spks)
        train_writer.close()
        val_writer.close()

    def transform(self):
        """Transform dataset from raw wave to compressed numpy array"""
        feat_extract_engine = FeatureExtraction(self.args)
        data = feat_extract_engine.process_raw_dataset()
        feat_extract_engine.save_as_ndarray(data[0], data[1], data[2], data[3])

        
def get_audio_properties(fname):
    with contextlib.closing(wave.open(fname,'r')) as f:
        frames = f.getnframes()
        rate = f.getframerate()
        duration = frames / float(rate)
        return duration, rate
    
    
def check_valid_audio(files, duration_lim=1.5, sr=8000):
    filtered_list = []
    files = [str(path) for path in files]
    
    for fname in files:
        duration, rate = get_audio_properties(fname)
        if rate == sr and duration >= duration_lim:
            filtered_list.append(fname)
        else:
            pass
    filtered_list.sort(reverse=True, key = lambda x: get_audio_properties(x)[0])    
    filtered_list = [Path(path) for path in filtered_list]
    return filtered_list
    

def restore_dataset(raw_dataset):
    raw_data_dir = raw_dataset

    data_paths = []
    for fdir in os.listdir(raw_data_dir):
        data_paths.extend(
            glob.glob(os.path.join(raw_data_dir, f'{fdir}/*.wav')))

    raw_paths = list(
        filter(lambda x: 'augment' not in str(x) and 'vad' not in str(x), data_paths))
    extended_paths = list(filter(lambda x: x not in raw_paths, data_paths))
    augment_paths = list(filter(lambda x: 'augmented' in str(x), data_paths))
    vad_paths = list(filter(lambda x: 'vad' in str(x), data_paths))

    print(len(raw_paths), '/', len(extended_paths))
    print(len(augment_paths), '/', len(vad_paths))

    for audio_path in tqdm(extended_paths):
        if os.path.isfile(audio_path):
            os.remove(audio_path)
            pass
        else:
            pass


def vad_on_dataset(raw_dataset, save_dir):
    raw_data_dir = raw_dataset
    vad_engine = VAD()

    data_paths = []
    for fdir in os.listdir(raw_data_dir):
        data_paths.extend(
            glob.glob(os.path.join(raw_data_dir, f'{fdir}/*.wav')))

    # filters audiopaths
    raw_paths = list(
        filter(lambda x: 'augment' not in str(x) and 'vad' not in str(x), data_paths))

    for audio_path in tqdm(raw_paths):
        vad_engine.detect(audio_path)
    print("Done!")


parser = argparse.ArgumentParser(description="Data preparation")
if __name__ == '__main__':
    parser.add_argument('--save_dir',
                        type=str,
                        default="dataset/",
                        help='Directory to save files(parent root)')
    parser.add_argument('--raw_dataset',
                        type=str,
                        default="dataset/wavs",
                        help='Deractory consists raw dataset')
    parser.add_argument('--details_dir',
                        type=str,
                        default='dataset/train_details_full/',
                        help='Download and extract augmentation files')

    parser.add_argument('--split_ratio',
                        type=float,
                        default=0.2,
                        help='Split ratio')
    parser.add_argument('--num_spks',
                        type=int,
                        default=-1,
                        help='number of speaker')   
    # mode
    parser.add_argument('--convert',
                        default=False,
                        action='store_true',
                        help='Enable coversion')
    parser.add_argument('--generate',
                        default=False,
                        action='store_true',
                        help='Enable generate')
    parser.add_argument('--transform',
                        default=False,
                        action='store_true',
                        help='Enable transformation')
    parser.add_argument('--restore',
                        default=False,
                        action='store_true',
                        help='Restore dataset to origin(del augment and vad)')
    # augmentation
    parser.add_argument('--augment',
                        default=False,
                        action='store_true',
                        help='Download and extract augmentation files')
    parser.add_argument('--augment_mode',
                        type=str,
                        default='train',
                        help='')
    parser.add_argument('--augment_path',
                        type=str,
                        default='dataset/augment_data',
                        help='Directory include augmented data')
    parser.add_argument('--aug_rate',
                        type=float,
                        default=0.5,
                        help='')


    args = parser.parse_args()

    data_generator = DataGenerator(args)
    print('Start processing...')

    if args.augment:
        augmentation(
            args=args, audio_paths=data_generator.data_paths[0][:], step_save=200, mode=args.augment_mode)
    if args.convert:
        data_generator.convert()
    if args.generate:
        data_generator.generate_lists()
    if args.transform:
        data_generator.transform()
    if args.restore:
        restore_dataset(args.raw_dataset)