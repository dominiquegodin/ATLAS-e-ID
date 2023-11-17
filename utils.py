import tensorflow        as tf
import numpy             as np
import multiprocessing   as mp
import matplotlib.pyplot as plt
import os, sys, h5py, pickle, time, itertools, warnings
from   sklearn  import metrics, utils, preprocessing
from   tabulate import tabulate
from   skimage  import transform
from   plots_DG import var_histogram, plot_discriminant, plot_ROC_curves
from   plots_DG import ratio_plots, performance_ratio, performance_plots, plot_classes
from   plots_KM import plot_distributions_KM, differential_plots


#################################################################################
##### classifier.py functions ###################################################
#################################################################################


def sample_histograms(valid_sample, valid_labels, train_sample, train_labels, n_etypes, weights, bins, output_dir):
    arguments = [(valid_sample, valid_labels, n_etypes, None, bins, output_dir, 'valid')]
    if np.any(train_labels) != None:
        arguments += [(train_sample, train_labels, n_etypes, weights, bins, output_dir, 'train')]
    processes = [mp.Process(target=var_histogram, args=arg+(var,)) for arg in arguments for var in ['pt','eta']]
    for job in processes: job.start()
    for job in processes: job.join()


def split_samples(valid_sample, valid_labels, train_sample, train_labels):
    #generate a different validation sample from training sample with downsampling
    valid_sample, valid_labels, extra_sample, extra_labels = downsampling(valid_sample, valid_labels)
    train_sample  = {key:np.concatenate([train_sample[key], extra_sample[key]]) for key in train_sample}
    train_labels  = np.concatenate([train_labels, extra_labels])
    sample_weight = match_distributions(train_sample, train_labels, valid_sample, valid_labels)
    return valid_sample, valid_labels, train_sample, train_labels, sample_weight


def get_class_weight(labels, bkg_ratio):
    n_e = len(labels); n_classes = max(labels) + 1
    if bkg_ratio == 0 and n_classes == 2: return None
    if bkg_ratio == 0 and n_classes != 2: bkg_ratio = 1
    ratios       = {**{0:1}, **{n:bkg_ratio for n in np.arange(1, n_classes)}}
    class_weight = {n:n_e/np.sum(labels==n)*ratios[n]/sum(ratios.values()) for n in np.arange(n_classes)}
    return class_weight


def get_sample_weights(sample, labels, weight_type=None, bkg_ratio=None, hist='2d', ref_class=0, density=False):
    if weight_type not in ['bkg_ratio', 'flattening', 'match2class', 'match2max']: return None, None
    pt = sample['pt']; eta = abs(sample['eta']); n_classes = max(labels)+1
    n_bins   = 100; base = (np.max(pt)/np.min(pt))**(1/n_bins)
    pt_bins  = [np.min(pt)*base**n for n in np.arange(n_bins+1)]
    pt_bins[-1]  = max( pt_bins[-1], max( pt)) + 1e-3
    n_bins   = 50; step = np.max(eta)/n_bins
    eta_bins = np.arange(np.min(eta), np.max(eta)+step, step)
    eta_bins[-1] = max(eta_bins[-1], max(eta)) + 1e-3
    if hist == 'pt' : eta_bins = [eta_bins[0], eta_bins[-1]]
    if hist == 'eta':  pt_bins = [ pt_bins[0],  pt_bins[-1]]
    pt_ind   = np.digitize( pt,  pt_bins, right=False) -1
    eta_ind  = np.digitize(eta, eta_bins, right=False) -1
    hist_ref = np.histogram2d(pt[labels==ref_class], eta[labels==ref_class],
                              bins=[pt_bins,eta_bins], density=density)[0]
    if density: hist_ref *= np.sum(labels==ref_class)
    hist_ref = np.maximum(hist_ref, np.min(hist_ref[hist_ref!=0]))
    total_ref_array = []; total_bkg_array = []; hist_bkg_array = []
    if np.isscalar(bkg_ratio):
        bkg_ratio = n_classes*[bkg_ratio]
        #bkg_ratio = [0.25, 1, 1, 1, 1, 1] #; bkg_ratio[-1] = 0.1
        #bkg_ratio = [1, 5, 5, 5, 1, 1]
    for n in [n for n in np.arange(n_classes) if n != ref_class]:
        hist_bkg = np.histogram2d(pt[labels==n], eta[labels==n], bins=[pt_bins,eta_bins], density=density)[0]
        if density: hist_bkg *= np.sum(labels==n)
        hist_bkg = np.maximum(hist_bkg, np.min(hist_bkg[hist_bkg!=0]))
        ratio    = np.sum(hist_bkg)/np.sum(hist_ref) if bkg_ratio == None else bkg_ratio[n]
        if   weight_type == 'bkg_ratio':
            total_ref = hist_ref * max(1, np.sum(hist_bkg)/np.sum(hist_ref)/ratio)
            total_bkg = hist_bkg * max(1, np.sum(hist_ref)/np.sum(hist_bkg)*ratio)
        elif weight_type == 'flattening':
            total_ref = np.ones(hist_ref.shape) * max(np.max(hist_ref), np.max(hist_bkg)/ratio)
            total_bkg = np.ones(hist_bkg.shape) * max(np.max(hist_bkg), np.max(hist_ref)*ratio)
        elif weight_type == 'match2class':
            total_ref = hist_ref * max(1, np.max(hist_bkg/hist_ref)/ratio)
            total_bkg = hist_ref * max(1, np.max(hist_bkg/hist_ref)/ratio) * ratio
        elif weight_type == 'match2max':
            total_ref = np.maximum(hist_ref, hist_bkg/ratio)
            total_bkg = np.maximum(hist_bkg, hist_ref*ratio)
        total_ref_array.append(total_ref[np.newaxis,...])
        total_bkg_array.append(total_bkg[np.newaxis,...])
        hist_bkg_array.append ( hist_bkg[np.newaxis,...])
    hist_ref_array  = hist_ref[np.newaxis,...]
    hist_bkg_array  = np.concatenate( hist_bkg_array, axis=0)
    total_ref_array = np.concatenate(total_ref_array, axis=0)
    total_bkg_array = np.concatenate(total_bkg_array, axis=0)
    total_ref_ratio = total_ref_array / np.max(total_ref_array, axis=0)
    total_ref_array = np.max(total_ref_array, axis=0)
    total_bkg_array = total_bkg_array / total_ref_ratio
    weights_array = np.concatenate([total_ref_array/hist_ref_array, total_bkg_array/hist_bkg_array])
    sample_weight = np.zeros(len(labels), dtype=np.float32)
    class_list    = [ref_class] + [n for n in np.arange(n_classes) if n != ref_class]
    for n in np.arange(n_classes):
        sample_weight = np.where(labels==class_list[n], weights_array[n,...][pt_ind, eta_ind], sample_weight)
    return sample_weight*len(labels)/np.sum(sample_weight), {'pt':pt_bins, 'eta':eta_bins}


def gen_weights(n_train, weight_idx, sample_weight):
    weights = np.zeros(np.diff(n_train)[0])
    np.put(weights, weight_idx, sample_weight)
    return weights


def upsampling(sample, labels, bins, indices, hist_sig, hist_bkg, total_sig, total_bkg):
    new_sig = np.int_(np.around(total_sig)) - hist_sig
    new_bkg = np.int_(np.around(total_bkg)) - hist_bkg
    ind_sig = [np.where((indices==n) & (labels==0))[0] for n in np.arange(len(bins)-1)]
    ind_bkg = [np.where((indices==n) & (labels!=0))[0] for n in np.arange(len(bins)-1)]
    np.random.seed(0)
    ind_sig = [np.append(ind_sig[n], np.random.choice(ind_sig[n], new_sig[n],
               replace = len(ind_sig[n])<new_sig[n])) for n in np.arange(len(bins)-1)]
    ind_bkg = [np.append(ind_bkg[n], np.random.choice(ind_bkg[n], new_bkg[n],
               replace = len(ind_bkg[n])<new_bkg[n])) for n in np.arange(len(bins)-1)]
    indices = np.concatenate(ind_sig + ind_bkg); np.random.shuffle(indices)
    return {key:np.take(sample[key], indices, axis=0) for key in sample}, np.take(labels, indices)


def downsampling(sample, labels, bkg_ratio=None):
    pt = sample['p_et_calo']; bins = [0, 10, 20, 30, 40, 60, 80, 100, 130, 180, 250, 500]
    indices  = np.digitize(pt, bins, right=True) -1
    hist_sig = np.histogram(pt[labels==0], bins)[0]
    hist_bkg = np.histogram(pt[labels!=0], bins)[0]
    if bkg_ratio == None: bkg_ratio = np.sum(hist_bkg)/np.sum(hist_sig)
    total_sig = np.int_(np.around(np.minimum(hist_sig, hist_bkg/bkg_ratio)))
    total_bkg = np.int_(np.around(np.minimum(hist_bkg, hist_sig*bkg_ratio)))
    ind_sig   = [np.where((indices==n) & (labels==0))[0][:total_sig[n]] for n in np.arange(len(bins)-1)]
    ind_bkg   = [np.where((indices==n) & (labels!=0))[0][:total_bkg[n]] for n in np.arange(len(bins)-1)]
    valid_ind = np.concatenate(ind_sig+ind_bkg); np.random.seed(0); np.random.shuffle(valid_ind)
    train_ind = list(set(np.arange(len(pt))) - set(valid_ind))
    valid_sample = {key:np.take(sample[key], valid_ind, axis=0) for key in sample}
    valid_labels = np.take(labels, valid_ind)
    extra_sample = {key:np.take(sample[key], train_ind, axis=0) for key in sample}
    extra_labels = np.take(labels, train_ind)
    return valid_sample, valid_labels, extra_sample, extra_labels


def match_distributions(sample, labels, target_sample, target_labels):
    pt = sample['p_et_calo']; target_pt = target_sample['p_et_calo']
    bins = [0, 10, 20, 30, 40, 60, 80, 100, 130, 180, 250, 500]
    indices         = np.digitize(pt, bins, right=False) -1
    hist_sig        = np.histogram(       pt[labels==0]       , bins)[0]
    hist_bkg        = np.histogram(       pt[labels!=0]       , bins)[0]
    hist_sig_target = np.histogram(target_pt[target_labels==0], bins)[0]
    hist_bkg_target = np.histogram(target_pt[target_labels!=0], bins)[0]
    total_sig   = hist_sig_target * np.max(np.append(hist_sig/hist_sig_target, hist_bkg/hist_bkg_target))
    total_bkg   = hist_bkg_target * np.max(np.append(hist_sig/hist_sig_target, hist_bkg/hist_bkg_target))
    weights_sig = total_sig/hist_sig * len(labels)/np.sum(total_sig+total_bkg)
    weights_bkg = total_bkg/hist_bkg * len(labels)/np.sum(total_sig+total_bkg)
    return np.where(labels==0, weights_sig[indices], weights_bkg[indices])


def get_dataset(input_path='', input_dir='', host_name='lps'):
    if 'lps'    in host_name and input_path == '': input_path = '/opt/tmp/godin/e-ID_data/presamples'
    if 'beluga' in host_name and input_path == '': input_path = '/project/def-arguinj/shared/e-ID_data'
    if input_dir != '':
        folder = input_path+'/'+input_dir
        data_files = sorted([folder+'/'+h5_file for h5_file in os.listdir(folder) if '.h5' in h5_file])
    else:
        barrel_dir, midgap_dir, endcap_dir = [input_path+'/'+folder for folder in ['0.0-1.3', '1.3-1.6', '1.6-2.5']]
        barrel_files = sorted([barrel_dir+'/'+h5_file for h5_file in os.listdir(barrel_dir) if 'e-ID_' in h5_file])
        midgap_files = sorted([midgap_dir+'/'+h5_file for h5_file in os.listdir(midgap_dir) if 'e-ID_' in h5_file])
        endcap_files = sorted([endcap_dir+'/'+h5_file for h5_file in os.listdir(endcap_dir) if 'e-ID_' in h5_file])
        data_files = [h5_file for group in zip(barrel_files, midgap_files, endcap_files) for h5_file in group]
    return data_files


def make_sample(data_file, idx, input_data, n_tracks, n_classes, verbose='OFF', prefix='p_', preprocess=False):
    scalars, images, others = input_data.values()
    if verbose == 'ON':
        print('Loading sample [', format(str(idx[0]),'>8s')+', '+format(str(idx[1]),'>8s'), end='] ')
        print('from', data_file.split('/')[-2]+'/'+data_file.split('/')[-1], end=' --> ', flush=True)
        start_time = time.time()
    with h5py.File(data_file, 'r') as data:
        sample = {key:data[key][idx[0]:idx[1]] for key in set(scalars+others)-{'tracks'}}
        sample.update({'eta'      :sample['p_eta'], 'pt':sample['p_et_calo'],
                       'mu'       :sample['averageInteractionsPerCrossing' ],
                       'SCTHits'  :sample['p_numberOfSCTHits'              ],
                       'PixelHits':sample['p_numberOfPixelHits'            ],
                       'BLHits'   :sample['p_numberOfInnermostPixelHits'   ]})
        for key in set(images)-{'tracks'}:
            try:
                sample[key] = data[key][idx[0]:idx[1]]
            except KeyError:
                if 'fine' in key: sample[key] = np.zeros((idx[1]-idx[0],)+(56,11))
                else            : sample[key] = np.zeros((idx[1]-idx[0],)+( 7,11))
        if 'tracks' in scalars+images:
            n_tracks    = min(n_tracks, data[prefix+'tracks'].shape[1])
            tracks_data = data[prefix+'tracks'][idx[0]:idx[1]][:,:n_tracks,:]
            tracks_data = np.concatenate((abs(tracks_data[...,0:5]), tracks_data[...,5:13]), axis=2)
            #tracks_data = np.concatenate((abs(tracks_data[...,0:5]), tracks_data[...,5:6], tracks_data[...,7:13]), axis=2)
            sample['tracks'] = tracks_data
    if tf.__version__ < '2.1.0':
        for key in set(sample)-set(others): sample[key] = np.float32(sample[key])
    if images == ['tracks']: sample['tracks'] = np.float32(sample['tracks'])
    labels = make_labels(sample, n_classes)
    if verbose == 'ON': print('(', '\b'+format(time.time() - start_time, '2.1f'), '\b'+' s)')
    if preprocess and images != []: sample = process_images(sample, images, verbose)
    return sample, labels


def make_labels(sample, n_classes, data_LF=False, match_to_vertex=False):
    iffTruth           = 'p_iffTruth'
    TruthType          = 'p_TruthType'
    firstEgMotherPdgId = 'p_firstEgMotherPdgId'
    charge             = 'p_charge'
    vertexIndex        = 'p_vertexIndex'
    labels = np.full_like(sample[iffTruth], -1)
    labels[(sample[iffTruth] ==  2) & (sample[firstEgMotherPdgId]*sample[charge] < 0)] = 0
    labels[(sample[iffTruth] ==  2) & (sample[firstEgMotherPdgId]*sample[charge] > 0)] = 1
    labels[ sample[iffTruth] ==  3                                                   ] = 1
    labels[ sample[iffTruth] ==  5                                                   ] = 2
    labels[(sample[iffTruth] ==  8) | (sample[iffTruth ] ==  9)                      ] = 3
    labels[(sample[iffTruth] == 10) & (sample[TruthType] ==  1)                      ] = 4
    labels[(sample[iffTruth] == 10) & (sample[TruthType] ==  4)                      ] = 4
    labels[(sample[iffTruth] == 10) & (sample[TruthType] == 16)                      ] = 4
    labels[(sample[iffTruth] == 10) & (sample[TruthType] == 17)                      ] = 5
    #labels[(sample[iffTruth] ==  1)] = 6 #KnowUnknown class
    if data_LF:
        labels[(labels == 4) | (labels == 5)]                      = -1
        labels[(sample[iffTruth] == 0) & (sample[TruthType] == 0)] =  4
    if n_classes == 2:
        labels[labels >= 2] = 1
    if n_classes == 5:
        #labels[labels >= 1] = labels[labels >= 1] -1 #signal = electron + chargeflip
        labels[labels == 5] = 4                      #light flavor = egamma + hadrons

    '''
    if n_classes == 2:
        labels = np.full_like(sample[iffTruth], -1)
        labels[(sample[iffTruth] ==  0) & (sample[TruthType] ==  0)] = 0
        labels[(sample[iffTruth] == 10) & (sample[TruthType] ==  4)] = 1
        labels[(sample[iffTruth] == 10) & (sample[TruthType] == 16)] = 1
        labels[(sample[iffTruth] == 10) & (sample[TruthType] == 17)] = 1
        #labels[(sample[iffTruth] == 10) & (sample[TruthType] ==  4)] = 0
        #labels[(sample[iffTruth] == 10) & (sample[TruthType] == 16)] = 0
        #labels[(sample[iffTruth] == 10) & (sample[TruthType] == 17)] = 0
        #event_number = sample['eventNumber']
        #labels[(event_number%2 == 1) & (labels == 0)] = 1
    '''

    if n_classes == 8:
        labels = np.full_like(sample[iffTruth], -1)
        labels[(sample[iffTruth] ==  2) & (sample[firstEgMotherPdgId]*sample[charge] < 0)] = 0
        labels[(sample[iffTruth] ==  2) & (sample[firstEgMotherPdgId]*sample[charge] > 0)] = 1
        labels[ sample[iffTruth] ==  3                                                   ] = 1
        labels[ sample[iffTruth] ==  5                                                   ] = 2
        labels[ sample[iffTruth] ==  8                                                   ] = 3
        labels[ sample[iffTruth] ==  9                                                   ] = 4
        labels[(sample[iffTruth] == 10) & (sample[TruthType] ==  4)                      ] = 5
        labels[(sample[iffTruth] == 10) & (sample[TruthType] == 16)                      ] = 6
        labels[(sample[iffTruth] == 10) & (sample[TruthType] == 17)                      ] = 7

    if match_to_vertex:
        labels[sample[vertexIndex] == -999] = -1
    return np.int8(labels)


def batch_idx(data_files, batch_size, interval, weights=None, shuffle='OFF'):
    def return_idx(n_e, cum_batches, batch_size, index):
        file_index  = np.searchsorted(cum_batches, index, side='right')
        batch_index = index - np.append(0, cum_batches)[file_index]
        idx         = batch_index*batch_size; idx = [idx, min(idx+batch_size, n_e[file_index])]
        return file_index, idx
    n_e = [len(h5py.File(data_file,'r')['eventNumber']) for data_file in data_files]
    cum_batches = np.cumsum(np.int_(np.ceil(np.array(n_e)/batch_size)))
    indexes     = [return_idx(n_e, cum_batches, batch_size, index) for index in np.arange(cum_batches[-1])]
    cum_n_e     = np.cumsum(np.diff(list(zip(*indexes))[1]))
    n_e_index   = np.searchsorted(cum_n_e, [interval[0],interval[1]-1], side='right')
    batch_list  = [indexes[n] for n in np.arange(cum_batches[-1]) if n >= n_e_index[0] and n <= n_e_index[1]]
    cum_n_e     = [cum_n_e[n] for n in np.arange(cum_batches[-1]) if n >= n_e_index[0] and n <= n_e_index[1]]
    batch_list[ 0][1][0] = batch_list[ 0][1][1] + interval[0] - cum_n_e[ 0]
    batch_list[-1][1][1] = batch_list[-1][1][1] + interval[1] - cum_n_e[-1]
    if shuffle == 'ON': batch_list = utils.shuffle(batch_list, random_state=0)
    batch_dict = {batch_list.index(n):{'file':n[0], 'indices':n[1], 'weights':None} for n in batch_list}
    if np.all(weights) != None:
        weights = np.split(weights, np.cumsum(n_e))
        for n in batch_list: batch_dict[batch_list.index(n)]['weights'] = weights[n[0]][n[1][0]:n[1][1]]
    #for key in batch_dict: print(key, batch_dict[key])
    return batch_dict


def merge_samples(data_files, idx, input_data, n_tracks, n_classes, cuts, scaler=None, t_scaler=None):
    batch_dict = batch_idx(data_files, np.diff(idx)[0], idx)
    samples, labels = zip(*[make_sample(data_files[batch_dict[key]['file']], batch_dict[key]['indices'],
                            input_data, n_tracks, n_classes, verbose='ON') for key in batch_dict])
    labels = np.concatenate(labels); sample = {}
    for key in list(samples[0].keys()):
        sample[key] = np.concatenate([n[key] for n in samples])
        for n in samples: n.pop(key)
    cut_list = [np.full_like(labels, True, dtype=bool)]
    for cut in cuts:
        try   : cut_list.append(eval(cut))
        except: pass
    eval_cuts = np.logical_and.reduce(cut_list)
    indices = np.where( np.logical_and(labels!=-1, eval_cuts if cuts!='' else True) )[0]
    sample, labels, _ = sample_cuts(sample, labels, cuts=cuts, verbose='ON')
    if   scaler != None: sample = apply_scaler(sample, input_data['scalars'], scaler, verbose='ON')
    if t_scaler != None: sample = apply_t_scaler(sample, t_scaler, verbose='ON')
    else: print()
    return sample, labels, indices


class Batch_Generator(tf.keras.utils.Sequence):
    def __init__(self, data_files, indexes, input_data, n_tracks, n_classes,
                 batch_size, cuts, scaler, t_scaler, weights=None, shuffle='OFF'):
        self.data_files = data_files; self.indexes    = indexes
        self.input_data = input_data; self.n_tracks   = n_tracks
        self.n_classes  = n_classes ; self.batch_size = batch_size
        self.cuts       = cuts      ; self.scaler     = scaler ;self.t_scaler = t_scaler
        self.weights    = weights   ; self.shuffle    = shuffle
        self.batch_dict = batch_idx(self.data_files, self.batch_size, self.indexes, self.weights, self.shuffle)
    def __len__(self):
        return len(self.batch_dict) #Number of batches per epoch
    def __getitem__(self, gen_index):
        file_index = self.batch_dict[gen_index]['file']
        file_idx   = self.batch_dict[gen_index]['indices']
        weights    = self.batch_dict[gen_index]['weights']
        data_file  = self.data_files[file_index]
        sample, labels = make_sample(data_file, file_idx, self.input_data, self.n_tracks, self.n_classes)
        sample, labels, weights = sample_cuts(sample, labels, weights, self.cuts)
        if len(labels) != 0:
            if self.scaler   != None: sample = apply_scaler(sample, self.input_data['scalars'], self.scaler)
            if self.t_scaler != None: sample = apply_t_scaler(sample, self.t_scaler)
        return sample, labels, weights


def sample_cuts(sample, labels, weights=None, cuts='', verbose='OFF'):
    if np.sum(labels==-1) != 0:
        length = len(labels)
        sample = {key:sample[key][labels!=-1] for key in sample}
        if np.all(weights) != None: weights = weights[labels!=-1]
        labels = labels[labels!=-1]
        if verbose == 'ON':
            print('Applying IFFtruth cuts -->', format(len(labels),'9d'), 'e conserved', end=' ')
            print('(' + format(100*len(labels)/length, '.2f') + ' %)')
    cut_list = [np.full_like(labels, True, dtype=bool)]
    for cut in cuts:
        try:
            cut_list.append(eval(cut))
        except:
            if verbose == 'ON' and cut != '': print('WARNING --> invalid cut:' , cut)
    eval_cuts = np.logical_and.reduce(cut_list)
    length = len(labels)
    labels = labels[eval_cuts]
    if np.all(weights) != None: weights = weights[eval_cuts]
    sample = {key:sample[key][eval_cuts] for key in sample}
    if verbose == 'ON':
        print('Applying selected cuts -->', format(len(labels),'9d') ,'e conserved', end=' ')
        print('(' + format(100*len(labels)/length,'.2f')+' %)')
        #if len(labels) < length: print('Applied cuts:', cuts[0]+' & ...')
    return sample, labels, weights


def process_images(sample, image_list, verbose='OFF'):
    if image_list == []: return sample
    if verbose == 'ON':
        start_time = time.time()
        print('Processing images for best axis', end=' --> ', flush=True)
    for cal_image in [key for key in image_list if 'tracks' not in key]:
        images = sample[cal_image]
        images = images.T
        #images  = abs(images)                               # negatives to positives
        #images -= np.minimum(0, np.min(images, axis=(0,1))) # shift to positive domain
        images = np.maximum(0, images)                       # clips negative values
        mean_1 = np.mean(images[:images.shape[0]//2   ], axis=(0,1))
        mean_2 = np.mean(images[ images.shape[0]//2:-1], axis=(0,1))
        images = np.where(mean_1 > mean_2, images[::-1,::-1,:], images).T
        sample[cal_image] = images
    if verbose == 'ON': print('('+format(time.time()-start_time,'.1f'), '\b'+' s)')
    return sample


def process_images_mp(sample, image_list, verbose='OFF', n_tasks=16):
    if image_list == []: return sample
    def rotation(images, indices, return_dict):
        images = images[indices[0]:indices[1]].T
        #images  = abs(images)                               # negatives to positives
        #images -= np.minimum(0, np.min(images, axis=(0,1))) # shift to positive domain
        images = np.maximum(0, images)                       # clips negative values
        mean_1 = np.mean(images[:images.shape[0]//2   ], axis=(0,1))
        mean_2 = np.mean(images[ images.shape[0]//2:-1], axis=(0,1))
        return_dict[indices] = np.where(mean_1 > mean_2, images[::-1,::-1,:], images).T
    n_samples = len(sample['eventNumber'])
    idx_list  = [task*(n_samples//n_tasks) for task in np.arange(n_tasks)] + [n_samples]
    idx_list  = list( zip(idx_list[:-1], idx_list[1:]) )
    if verbose == 'ON':
        start_time = time.time()
        print('Processing images for best axis', end=' --> ', flush=True)
    for cal_image in [key for key in image_list if 'tracks' not in key]:
        images    = sample[cal_image]; manager = mp.Manager(); return_dict = manager.dict()
        processes = [mp.Process(target=rotation, args=(images, idx, return_dict)) for idx in idx_list]
        for job in processes: job.start()
        for job in processes: job.join()
        sample[cal_image] = np.concatenate([return_dict[idx] for idx in idx_list])
    if verbose == 'ON': print('('+format(time.time()-start_time,'.1f'), '\b'+' s)')
    return sample


def fit_scaler(sample, scalars, scaler_out):
    print('Fitting quantile transform from scalars', end=' --> ', flush=True); start_time = time.time()
    scalars = [key for key in scalars if key != 'tracks']
    scalars_array = np.hstack([np.expand_dims(np.float32(sample[key]), axis=1) for key in scalars])
    scaler = preprocessing.QuantileTransformer(output_distribution='normal', n_quantiles=10000, random_state=0)
    scaler.fit(scalars_array) #scaler.fit_transform(scalars_array)
    print('(', '\b'+format(time.time() - start_time, '2.1f'), '\b'+' s)')
    print('Saving  quantile transform to', scaler_out, '\n')
    pickle.dump(scaler, open(scaler_out, 'wb'))
    return scaler


def apply_scaler(sample, scalars, scaler, verbose='OFF'):
    if verbose == 'ON':
        print('Applying quantile transform to scalars', end=' --> ', flush=True); start_time = time.time()
    scalars = [key for key in scalars if key != 'tracks']
    scalars_array = scaler.transform(np.hstack([np.expand_dims(np.float32(sample[key]), axis=1) for key in scalars]))
    for n in np.arange(len(scalars)): sample[scalars[n]] = scalars_array[:,n]
    if verbose == 'ON': print('(', '\b'+format(time.time() - start_time, '2.1f'), '\b'+' s)\n')
    return sample


def fit_t_scaler(sample, scaler_out):
    print('Fitting  quantile transform from tracks', end='  --> ', flush=True); start_time = time.time()
    tracks = sample['tracks']; shape = tracks.shape
    #scaler = preprocessing.QuantileTransformer(output_distribution='normal', n_quantiles=10000, random_state=0)
    scaler = preprocessing.RobustScaler()
    scaler.fit(np.reshape(tracks, (shape[0]*shape[1],-1)))
    print('(', '\b'+format(time.time() - start_time, '2.1f'), '\b'+' s)')
    print('Saving   tracks scaler file in', scaler_out, '\n')
    pickle.dump(scaler, open(scaler_out, 'wb'))
    return scaler


def apply_t_scaler(sample, scaler, verbose='OFF'):
    if verbose == 'ON':
        print('Applying quantile transform to tracks', end=' --> ', flush=True); start_time = time.time()
    tracks = sample['tracks']; shape = tracks.shape
    tracks = np.reshape(tracks, (shape[0]*shape[1],-1))
    tracks = scaler.transform(tracks)
    sample['tracks'] = np.reshape(tracks, shape)
    if verbose == 'ON': print('(', '\b'+format(time.time() - start_time, '2.1f'), '\b'+' s)\n')
    return sample


def sample_composition(sample, tag='valid'):
    MC_type, IFF_type = sample['p_TruthType']    , sample['p_iffTruth']
    MC_list, IFF_list = np.arange(max(MC_type)+1), np.arange(max(IFF_type)+1)
    ratios = np.array([ [np.sum(MC_type[IFF_type==IFF]==MC) for MC in MC_list] for IFF in IFF_list ])
    IFF_sum, MC_sum = 100*np.sum(ratios, axis=0)/len(MC_type), 100*np.sum(ratios, axis=1)/len(MC_type)
    ratios = np.round(1e4*ratios/len(MC_type))/100
    MC_empty, IFF_empty = np.where(np.sum(ratios, axis=0)==0)[0], np.where(np.sum(ratios, axis=1)==0)[0]
    MC_list,  IFF_list  = sorted(list(set(MC_list)-set(MC_empty))), sorted(list(set(IFF_list)-set(IFF_empty)))
    print('IFFTRUTH AND TRUTHTYPE '+tag.upper()+' SAMPLE COMPOSITION (', '\b'+str(len(MC_type)), 'e)')
    dash = (26+7*len(MC_list))*'-'
    print(dash, format('\n| IFF \ MC |','10s'), end='')
    for col in MC_list:
        print(format(col, '7.0f'), end='   |  Total  | \n' + dash + '\n' if col==MC_list[-1] else '')
    for row in IFF_list:
        print('|', format(row, '5.0f'), '   |', end='' )
        for col in MC_list:
            print(format(ratios[row,col], '7.0f' if ratios[row,col]==0 else '7.2f'), end='', flush=True)
        print('   |' + format(MC_sum[row], '7.2f')+ '  |')
        if row != IFF_list[-1]: print('|' + 10*' ' + '|' + (3+7*len(MC_list))*' ' + '|' + 9*' ' + '|')
    print(dash + '\n|   Total  |', end='')
    for col in MC_list: print(format(IFF_sum[col], '7.2f'), end='')
    print('   |  100 %  |\n' + dash + '\n')


def validation(output_dir, results_in, plotting, n_valid, n_etypes, valid_cuts):
    print('\nLOADING VALIDATION RESULTS FROM:', output_dir+'/'+results_in)
    if len(valid_cuts) >= 1:
        print('\nVALIDATION CUTS:')
        args_dict = {'valid_cuts':valid_cuts}
        if len(valid_cuts) > 1:
            for n in range(len(valid_cuts)): args_dict['valid_cuts ('+str(n+1)+')'] = valid_cuts[n]
            args_dict.pop('valid_cuts')
        print(tabulate(args_dict.items(), tablefmt='psql'), '\n')
    valid_data = pickle.load(open(output_dir+'/'+results_in, 'rb'))
    if len(valid_data) > 1: sample, labels, probs   = valid_data
    else:                                  (probs,) = valid_data
    n_e = min(len(probs), int(n_valid))
    sample, labels, probs = {key:sample[key][:n_e] for key in sample}, labels[:n_e], probs[:n_e]
    print('GENERATING PERFORMANCE RESULTS FOR', n_e, 'ELECTRONS', end='', flush=True)

    if n_etypes == 5 and probs.shape[-1] == 6:
        labels = np.where(labels==5, 4, labels)
    if n_etypes == 5 and probs.shape[-1] == 8:
        labels = np.where(labels==4, 3, labels)
        labels = np.where(labels==5, 4, labels)
        labels = np.where(labels==6, 4, labels)
        labels = np.where(labels==7, 4, labels)
    if n_etypes == 6 and probs.shape[-1] == 8:
        labels = np.where(labels==5, 5, labels)
        labels = np.where(labels==6, 5, labels)
        labels = np.where(labels==7, 5, labels)
    if n_etypes == 7 and probs.shape[-1] == 8:
        labels = np.where(labels==4, 3, labels)
        labels = np.where(labels==5, 4, labels)
        labels = np.where(labels==6, 5, labels)
        labels = np.where(labels==7, 6, labels)

    ratios = compo_matrix(labels, None, probs, n_etypes, verbose=False)
    cut_list = [np.full_like(labels, True, dtype=bool)]
    for cut in valid_cuts:
        try   : cut_list.append(eval(cut))
        except: pass
    cuts = np.logical_and.reduce(cut_list)
    sample, labels, probs = {key:sample[key][cuts] for key in sample}, labels[cuts], probs[cuts]
    if len(labels) == n_e: print('')
    else: print(' --> ('+str(len(labels))+' selected = '+format(100*len(labels)/n_e,'0.2f')+'%)')
    valid_results(sample, labels, probs, None, n_etypes, output_dir, plotting, ratios); print()
    #multi_cuts(sample, labels, probs, output_dir); sys.exit()
    #sample_histograms(sample, labels, None, None, weights=None, bins=None, output_dir=output_dir)


def class_ratios(labels, n_etypes):
    def get_ratios(labels, n, return_dict):
        return_dict[n] = 100*np.sum(labels==n)/len(labels)
    manager = mp.Manager(); return_dict = manager.dict()
    processes = [mp.Process(target=get_ratios, args=(labels, n, return_dict)) for n in range(n_etypes)]
    for job in processes: job.start()
    for job in processes: job.join()
    return [return_dict[n] for n in range(n_etypes)]


def confusion_matrix(labels, preds, n_etypes):
    def get_stat(labels, preds, classes, m, return_dict):
        selection = (preds==m) ; n_e = [np.sum(labels==n) for n in classes]
        return_dict[m] = [np.sum((selection)&(labels==n))/n_e[n] if n_e[n]!=0 else 0 for n in classes]
    classes = np.arange(n_etypes)
    #return metrics.confusion_matrix(labels, preds, normalize='true').T
    #return np.array([[np.sum((preds==m)&(labels==n))/np.sum(labels==n) for n in classes] for m in classes])
    manager   = mp.Manager(); return_dict = manager.dict()
    arguments = [(labels, preds, classes, m, return_dict) for m in classes]
    processes = [mp.Process(target=get_stat, args=arg) for arg in arguments]
    for task in processes: task.start()
    for task in processes: task.join()
    return np.array([return_dict[m] for m in classes])


def compo_matrix(valid_labels, train_labels=None, valid_probs=None, n_etypes=None, verbose=True):
    if n_etypes is None:
        if train_labels is not None: n_etypes = len(np.unique(np.append(valid_labels, train_labels)))
        else                       : n_etypes = len(np.unique(valid_labels))
    classes = ['CLASS '+str(n) for n in range(n_etypes)]
    train_ratios = class_ratios(train_labels, n_etypes) if train_labels is not None else n_etypes*['n/a']
    valid_ratios = class_ratios(valid_labels, n_etypes)
    #valid_ratios = [17.42, 0.523, 0.559, 1.532, 79.966]
    if valid_probs is None:
        print('+---------------------------------------+\n| CLASS DISTRIBUTIONS'+19*' '+'|')
        headers = ['CLASS #', 'TRAIN (%)', 'VALID (%)']
        table   = zip(classes, train_ratios, valid_ratios)
        print(tabulate(table, headers=headers, tablefmt='psql', floatfmt=".2f"))
    else:
        valid_preds = np.argmax(valid_probs, axis=1) if valid_probs is not None else valid_labels
        if verbose:
            matrix = 100*confusion_matrix(valid_labels, valid_preds, n_etypes)
            pred_ratios = matrix @ valid_ratios / 100
            classes = ['CLASS '+str(n) for n in range(n_etypes)]
            if n_etypes > 2:
                headers = ['CLASS #', 'TRAIN', 'VALID'] + classes + ['       VALID']
                table   = [classes] + [train_ratios] + [valid_ratios] + matrix.tolist() + [pred_ratios]
                table   = list(map(list, zip(*table)))
                print_dict[2]  = '+'+31*'-'+'+'+35*'-'+12*(n_etypes-3)*'-'+ '+'+16*'-'+  '+\n'
                print_dict[2] += '| CLASS DISTRIBUTIONS (%)       | VALID SAMPLE PREDICTIONS (%)      '
                print_dict[2] += 12*(n_etypes-3)*' ' + '| PREDICTIONS (%)|\n'
            else:
                headers = ['CLASS #', 'TRAIN (%)', 'VALID (%)', 'ACC. (%)']
                table   = zip(classes, train_ratios, valid_ratios, matrix.diagonal())
                print_dict[2]  = '+----------------------------------------------------+\n'
                print_dict[2] += '| CLASS DISTRIBUTIONS AND VALID SAMPLE ACCURACIES    |\n'
            valid_accuracy = valid_ratios @ matrix.diagonal() /100
            print_dict[2] += tabulate(table, headers=headers, tablefmt='psql', floatfmt=".2f")+'\n'
            print_dict[2] += 'VALIDATION SAMPLE ACCURACY: '+format(valid_accuracy,'.2f')+' %\n'
        else:
            #pred_ratios = 100*np.mean(valid_probs, axis=0, dtype=np.float64)
            pred_ratios = [100*np.sum(valid_preds==n)/len(valid_preds) for n in range(n_etypes)]
        # Light Flavor Ratios (classes 4 and 5 combined)
        #if n_etypes == 6:
        #    valid_ratios[4] = valid_ratios[5] + valid_ratios[4]
        #    valid_ratios[5] = valid_ratios[4]
        return {'truth':valid_ratios, 'pred':pred_ratios, 'none':np.ones_like(valid_ratios)}


def make_discriminant(sample, labels, probs, n_etypes, sig_list, bkg, ratios=None, verbose=False):
    n_classes = probs.shape[1]
    def class_weights(sig_list, ratios, optimal_bkg):
        weights = np.ones(n_classes) if ratios is None else ratios.copy()
        if optimal_bkg != 'bkg':
            for n in range(n_classes):
                if n not in sig_list and n != optimal_bkg: weights[n] = 0
        return np.array(weights)
    if n_classes > 2:
        """ Multi-class discriminant """
        bkg_list = list(set(np.arange(n_classes))-set(sig_list))
        bkg = bkg_list if bkg=='bkg' else [int(n) for n in str(bkg)]
        if verbose: print_dict[1] += 'SIGNAL = '+str(set(sig_list))+' vs BACKGROUND = '+str(set(bkg))+'\n'
        #for n in list(np.arange(1, n_classes))+['bkg']: print(n, class_weights(sig_list, ratios, n))
        weights = class_weights(sig_list, ratios, 'bkg')                              #Optimal combined background
        #weights = class_weights(sig_list, ratios, 'bkg' if bkg==bkg_list else bkg[0]) #Optimal individual classes
        sig_cut = np.logical_or.reduce([labels==n for n in sig_list])
        bkg_cut = np.logical_or.reduce([labels==n for n in bkg     ])
        all_cut = np.logical_or(sig_cut, bkg_cut)
        sample = {key:sample[key][all_cut] for key in sample}
        labels = np.where(sig_cut, 0, 1)[all_cut]
        #sig_probs = np.add.reduce([weights[n]*probs[:,n] for n in sig_list])[all_cut]
        #bkg_probs = np.add.reduce([weights[n]*probs[:,n] for n in bkg_list])[all_cut]
        sig_probs = (probs[:,sig_list]@weights[sig_list])[all_cut]
        bkg_probs = (probs[:,bkg_list]@weights[bkg_list])[all_cut]
        sig_probs = np.where(sig_probs!=bkg_probs, sig_probs, 0.5)
        bkg_probs = np.where(sig_probs!=bkg_probs, bkg_probs, 0.5)
        probs = (np.vstack([sig_probs,bkg_probs])/(sig_probs+bkg_probs)).T
    else:
        """ Background separation for binary classification """
        if bkg == 'bkg': return sample, labels, probs
        if verbose: print_dict[1] += 'SIGNAL = {0} VS BACKGROUND = {'+str(bkg)+'}\n'
        multi_labels = make_labels(sample, n_classes=n_etypes)
        cuts = np.logical_or(multi_labels==0, multi_labels==bkg)
        sample, labels, probs = {key:sample[key][cuts] for key in sample}, labels[cuts], probs[cuts]
    return sample, labels, probs


def print_results(sample, labels, probs, n_etypes, plotting, output_dir, sig_list, bkg,
                  ratios, return_dict, threshold, LF_cuts=None, sep_bkg=True, ECIDS=True):
    # Multi-discriminants
    #_, _, prob  = make_discriminant(sample, labels, probs, n_etypes, ig_list, bkg,
    #                                ratios=[17.43,0.,0.,0.,12.72,67.19])
    #LF_cuts = prob[:,0] > threshold
    sample, labels, probs = make_discriminant(sample, labels, probs, n_etypes, sig_list, bkg, ratios, verbose=True)
    if plotting == 'ON':
        output_dir += '/'+'class_'+''.join([str(n) for n in sig_list])+'vs'+str(bkg).title()
        if not os.path.isdir(output_dir): os.mkdir(output_dir)
        #for iter_tuple in itertools.product([False,True], ['CNN2LLH','CNN2CNN']):
        #    performance_ratio(sample, labels, probs[:,0], bkg, output_dir, *iter_tuple)
        #if bkg == 'bkg': performance_plots(sample, labels, probs[:,0], output_dir)
        ECIDS = ECIDS and bkg==1
        arguments  = [(sample, labels, probs[:,0], output_dir, ROC_type, ECIDS, LF_cuts) for ROC_type in [1]]
        processes  = [mp.Process(target=plot_ROC_curves, args=arg) for arg in arguments]
        #arguments  = (sample, labels, probs[:,0], n_etypes, output_dir, sep_bkg and bkg=='bkg' and n_etypes>2, bkg)
        #processes += [mp.Process(target=plot_discriminant, args=arguments)]
        for job in processes: job.start()
        for job in processes: job.join()
    else:
        compo_matrix(labels, None, probs)
        print_performance(labels, probs)
    return_dict[bkg] = print_dict


def valid_results(sample, labels, probs, train_labels, n_etypes, output_dir, plotting,
                  valid_ratios=None, sep_bkg=True, diff_plots=False, threshold=None):
    global print_dict; print_dict = {n:'' for n in [1,2,3]}; print()

    if n_etypes == 5 and probs.shape[-1] == 6:
        probs  = np.hstack([probs[:,:4], (probs[:,4]+probs[:,5])[:,None]])
    if n_etypes == 5 and probs.shape[-1] == 8:
        probs  = np.hstack([probs[:,:3], (probs[:,3]+probs[:,4])[:,None],
                            (probs[:,5]+probs[:,6]+probs[:,7])[:,None]])
    if n_etypes == 6 and probs.shape[-1] == 8:
        probs  = np.hstack([probs[:,:5], (probs[:,5]+probs[:,6]+probs[:,7])[:,None]])
    if n_etypes == 7 and probs.shape[-1] == 8:
        probs  = np.hstack([probs[:,:3], (probs[:,3]+probs[:,4])[:,None],
                            probs[:,5][:,None], probs[:,6][:,None], probs[:,7][:,None]])

    ratios = compo_matrix(labels, train_labels, probs, n_etypes) ; print(print_dict[2])
    if valid_ratios is not None: ratios = valid_ratios
    """ Plotting efficiciency ratios mesh grid """
    #ratio_plots(sample, labels, probs, n_etypes, output_dir)
    for sig_list in [[0]]:#,[0,1]]:
        # Multi-discriminants
        #first_cut_ratios = [17.4375,0.,0.,0.,12.7207,67.1977]
        #_, new_labels, new_probs = make_discriminant(sample, labels, probs, n_etypes,
        #                                             sig_list, 'bkg', ratios=first_cut_ratios)
        #_, tpr, thresholds = metrics.roc_curve(new_labels, new_probs[:,0], pos_label=0)
        #sig_eff=0.99 ; threshold = thresholds[np.argmin(abs(tpr-sig_eff))]
        #bkg_list = ['bkg'] + list(set(np.unique(labels))-set(sig_list)) if sep_bkg and n_etypes>2 else ['bkg']
        bkg_list = ['bkg']
        if sep_bkg and n_etypes >  2: bkg_list += list(set(np.unique(labels))-set(sig_list))
        if sep_bkg and n_etypes == 6: bkg_list += [45]
        manager   = mp.Manager(); return_dict = manager.dict()
        arguments = [(sample, labels, probs, n_etypes, plotting, output_dir, sig_list, bkg,
                      ratios['truth'], return_dict, threshold) for bkg in bkg_list]
        processes = [mp.Process(target=print_results, args=arg) for arg in arguments]
        for job in processes: job.start()
        for job in processes: job.join()
    #bkg_list  = {sig_list:['bkg'] + list(set(np.unique(labels))-set(sig_list)) if sep_bkg else ['bkg']
    #             for sig_list in [(0,),(0,1)][:1]}
    #manager   = mp.Manager(); return_dict = manager.dict()
    #arguments = [(sample, labels, probs, n_etypes, plotting, output_dir, list(sig_list), bkg,
    #              ratios['truth'], return_dict, threshold) for sig_list in bkg_list for bkg in bkg_list[sig_list]]
    #processes = [mp.Process(target=print_results, args=arg) for arg in arguments]
    #for job in processes: job.start()
    #for job in processes: job.join()
    """ Background rejection extraction for feature ranking """
    if plotting == 'OFF':
        for bkg in bkg_list: print("".join(list(return_dict[bkg].values())))
        return [int(return_dict[bkg][3].split()[-1]) for bkg in bkg_list]
    """ Differential plots """
    if plotting == 'ON' and diff_plots:
        eta_boundaries  = [-1.6, -0.8, 0, 0.8, 1.6]
        pt_boundaries   = [10, 20, 30, 40, 60, 100, 200, 500]
        eta, pt         = sample['eta'], sample['pt']
        eta_bin_indices = get_bin_indices(eta, eta_boundaries)
        pt_bin_indices  = get_bin_indices(pt , pt_boundaries)
        plot_distributions_KM(labels, eta, 'eta', output_dir=output_dir)
        plot_distributions_KM(labels, pt , 'pt' , output_dir=output_dir)
        tmp_llh      = sample['p_LHValue']
        tmp_llh_pair = np.zeros(len(tmp_llh))
        prob_LLH     = np.stack((tmp_llh,tmp_llh_pair),axis=-1)
        print('\nEvaluating differential performance in eta')
        differential_plots(sample, labels, probs, eta_boundaries,
                           eta_bin_indices, varname='eta', output_dir=output_dir)
        print('\nEvaluating differential performance in pt')
        differential_plots(sample, labels, probs, pt_boundaries,
                           pt_bin_indices,  varname='pt',  output_dir=output_dir)
        differential_plots(sample, labels, prob_LLH   , pt_boundaries,
                           pt_bin_indices,  varname='pt',  output_dir=output_dir, evalLLH=True)


def print_performance(labels, probs, sig_eff=[90, 80, 70]):
    fpr, tpr, _ = metrics.roc_curve(labels, probs[:,0], pos_label=0)
    fpr, tpr    = fpr[::-2][::-1], tpr[::-2][::-1] #for linear interpolation
    for val in sig_eff:
        print_dict[3] += 'BACKGROUND REJECTION AT '+str(val)+'%: '
        print_dict[3] += format(np.nan_to_num(1/fpr[np.argwhere(tpr>=val/100)[0]][0]),'>6.0f')+'\n'


def cross_valid(valid_sample, valid_labels, scalars, output_dir, n_folds, data_files, n_valid,
                input_data, n_tracks, valid_cuts, model, generator='OFF', verbose=1):
    print('########################################################################'  )
    print('##### STARTING '+str(n_folds)+'-FOLD CROSS-VALIDATION ################################'  )
    print('########################################################################\n')
    from plots_DG import valid_accuracy
    n_classes    = max(valid_labels)+1
    valid_probs  = np.full(valid_labels.shape + (n_classes,), -1.)
    event_number = valid_sample['eventNumber']
    for fold_number in np.arange(1, n_folds+1):
        print('FOLD '+str(fold_number)+'/'+str(n_folds), 'EVALUATION')
        weight_file = output_dir+'/model_' +str(fold_number)+'.h5'
        scaler_file = output_dir+'/scaler_'+str(fold_number)+'.pkl'
        print('Loading pre-trained weights from', weight_file)
        model.load_weights(weight_file); start_time = time.time()
        indices =               np.where(event_number%n_folds==fold_number-1)[0]
        labels  =           valid_labels[event_number%n_folds==fold_number-1]
        sample  = {key:valid_sample[key][event_number%n_folds==fold_number-1] for key in valid_sample}
        if scalars != [] and os.path.isfile(scaler_file):
            print('Loading scalars scaler from', scaler_file)
            scaler = pickle.load(open(scaler_file, 'rb'))
            sample = apply_scaler(sample, scalars, scaler, verbose='ON')
        print('\033[FCLASSIFIER:', weight_file.split('/')[-1], 'class predictions for', len(labels), 'e')
        if generator == 'ON':
            valid_cuts = '(sample["eventNumber"]%'+str(n_folds)+'=='+str(fold_number-1)+')'
            valid_gen  = Batch_Generator(data_files, n_valid, input_data, n_tracks, n_classes,
                                         batch_size=20000, cuts=valid_cuts, scaler=scaler)
            probs = model.predict(valid_gen, workers=4, verbose=verbose)
        else: probs = model.predict(sample, batch_size=20000, verbose=verbose)
        print('FOLD '+str(fold_number)+'/'+str(n_folds)+' ACCURACY: ', end='')
        print(format(100*valid_accuracy(labels, probs), '.2f'), end='')
        print(' % (', '\b'+format(time.time() - start_time, '2.1f'), '\b'+' s)\n')
        #for n in np.arange(len(indices)): valid_probs[indices[n],:] = probs[n,:]
        for n in np.arange(n_classes): np.put(valid_probs[:,n], indices, probs[:,n])
    print('MERGING ALL FOLDS AND PREDICTING CLASSES ...')
    return valid_probs


def multi_cuts(sample, labels, probs, output_dir, input_file=None, step=0.05, index=6, multi=False):
    import itertools; from functools import partial
    global efficiencies
    def get_eff(labels, cuts, class_type):
        class_cut = labels!=0 if class_type=='bkg' else labels==class_type
        return np.sum(np.logical_and(class_cut, cuts))/np.sum(class_cut)
    def classes_eff(labels, probs, fracs):
        cuts = probs[:,0] >= np.max(probs[:,1:]*(fracs/(1-fracs)), axis=1)
        return [get_eff(labels, cuts, class_type) for class_type in list(range(probs.shape[1]))+['bkg']]
    def apply_filter(ROC_values, index):
        pos_rates=[]; min_eff=1
        for n in np.arange(len(ROC_values)):
            if ROC_values[n][index] < min_eff:
                min_eff = ROC_values[n][index]
                pos_rates.append(ROC_values[n])
        return np.array(pos_rates)
    def get_pr(labels, disc):
        fpr, tpr, _  = metrics.roc_curve(labels, disc, pos_label=0)
        return fpr, tpr
    def get_auc(labels, disc, bkg, wps=[0.7,0.8,0.9]):
        cut = np.logical_or(labels==0, labels==bkg) if bkg != 'bkg' else np.full(len(labels), True, dtype=bool)
        fpr, tpr = get_pr(labels[cut], disc[cut])
        bkg_rej  = [1/fpr[np.argmin(abs(tpr-wp))] for wp in wps]
        return [metrics.auc(fpr,tpr)] + bkg_rej
    def classes_auc(labels, probs, fracs):
        disc = probs[:,0]/(probs[:,0]+(probs[:,1:]@fracs))
        bkg_list = ['bkg'] #+ list(range(1,probs.shape[1]))
        return np.ravel([get_auc(labels, disc, bkg) for bkg in bkg_list])
    def efficiencies(labels, probs, cut_tuples, multi, idx):
        func = classes_eff if multi else classes_auc
        return [list(func(labels, probs, cut_tuples[n]))+[cut_tuples[n]] for n in np.arange(idx[0],idx[1])]
    def ROC_curves(sample, labels, disc_list, bkg, output_dir):
        cut    = np.logical_or(labels==0, labels==bkg) if bkg != 'bkg' else np.full(len(labels), True, dtype=bool)
        sample = {key:sample[key][cut] for key in sample}; labels = labels[cut]
        ROC_values  = [get_pr(labels, disc[cut]) for disc in disc_list]
        output_dir += '/'+'class_0_vs_'+str(bkg); ROC_type = 2; ECIDS = bkg==1
        plot_ROC_curves(sample, labels, None, output_dir, ROC_type, ECIDS, ROC_values)
    input_file = 'pos_rates_step-0.05_mono2.pkl'
    if input_file == None:
        start_time = time.time()
        cut_list   = np.arange(0, 1, step)
        cut_tuples = np.array(list(itertools.product(cut_list,repeat=probs.shape[1]-1)))
        idx_tuples = get_idx(len(cut_tuples), n_sets=mp.cpu_count()); print(len(cut_tuples),'cuts')
        ROC_values = mp.Pool().map(partial(efficiencies, labels, probs, cut_tuples, multi), idx_tuples)
        ROC_values = np.concatenate(ROC_values)
        if multi:
            ROC_values = ROC_values[ROC_values[:,0].argsort()[::-1]]
        else:
            ROC_values = [ROC_values[np.argmax(ROC_values[:,n])] for n in range(ROC_values.shape[1]-1)]
            ROC_values = np.array([np.take(ROC_values[n], [n,-1]) for n in range(len(ROC_values))])
        pickle.dump(ROC_values, open(output_dir+'/'+'pos_rates_test.pkl','wb'))
        print('Run time:', format(time.time()-start_time, '2.2f'), '\b'+' s\n')
    else:
        ROC_values = pickle.load(open(output_dir+'/'+input_file,'rb'))

    if multi:
        for row in apply_filter(ROC_values, index):
            print(format(str(row[-1]),'30s')+' -->', format(100*row[0],'5.1f')+' % -->',
                  format(str([int(1/row[n]) for n in range(1,len(row)-1)]),'30s'))
    else:
        print(ROC_values)
        keys       = ['bkg']#list(range(1,probs.shape[1]))+['bkg']
        ROC_values = dict(zip(keys, ROC_values[:,1].reshape(len(keys),-1)))

    weigths_list = [np.array(class_ratios(labels)[1:])] + [n for n in ROC_values['bkg']]
    disc_list    = [probs[:,0]/(probs[:,0]+(probs[:,1:]@weights)) for weights in weigths_list]
    processes    = [mp.Process(target=ROC_curves, args=(sample, labels, disc_list, bkg, output_dir))
                    for bkg in list(range(1,6))+['bkg']]
    for job in processes: job.start()
    for job in processes: job.join()
    sys.exit()
    #ROC_values = (ROC_values[::int(np.ceil(ROC_values.shape[0]/10e6))], apply_filter(ROC_values, index))
    #ROC_values = (ROC_values[0][:,:-1], ROC_values[1][:,:-1])
    #processes  = [mp.Process(target=ROC_curves, args=(sample, labels, probs, bkg, ROC_values, output_dir))
    #              for bkg in list(range(1,ROC_values[0].shape[1]-1))+['bkg']]
    #for job in processes: job.start()
    #for job in processes: job.join()


def verify_sample(sample):
    def scan(sample, batch_size, index, return_dict):
        idx1, idx2 = index*batch_size, (index+1)*batch_size
        return_dict[index] = sum([np.sum(np.isfinite(sample[key][idx1:idx2])==False) for key in sample])
    n_e = len(list(sample.values())[0]); start_time = time.time()
    print('SCANNING', n_e, 'ELECTRONS FOR ERRORS -->', end=' ', flush=True)
    for n in np.arange(min(12, mp.cpu_count()), 0, -1):
        if n_e % n == 0: n_tasks = n; batch_size = n_e//n_tasks; break
    manager   =  mp.Manager(); return_dict = manager.dict()
    processes = [mp.Process(target=scan, args=(sample, batch_size, index, return_dict))
                for index in np.arange(n_tasks)]
    for job in processes: job.start()
    for job in processes: job.join()
    print(sum(return_dict.values()), 'ERRORS FOUND', end=' ', flush=True)
    print('(', '\b'+format(time.time() - start_time, '2.1f'), '\b'+' s)\n')
    if sum(return_dict.values()) != 0:
        for key in sample: print(key, np.where(np.isfinite(sample[key])==False))


def NN_weights(image_shape, CNN_dict, FCN_neurons, n_classes):
    kernels = np.array(CNN_dict[image_shape]['kernels']); n_maps = CNN_dict[image_shape]['maps']
    K = [image_shape[2] if len(image_shape)==3 else 1] + n_maps + FCN_neurons + [n_classes]
    A = [np.prod([image_shape[n] + sum(1-kernels)[n] for n in [0,1]])]
    A = [np.prod(kernels[n]) for n in np.arange(len(n_maps))] + A + len(FCN_neurons)*[1]
    return sum([(K[l]*A[l]+1)*K[l+1] for l in np.arange(len(K)-1)])


def order_kernels(image_shape, n_maps, FCN_neurons, n_classes):
    x_dims  = [(x1,x2) for x1 in np.arange(1,image_shape[0]+1) for x2 in np.arange(1,image_shape[0]-x1+2)]
    y_dims  = [(y1,y2) for y1 in np.arange(1,image_shape[1]+1) for y2 in np.arange(1,image_shape[1]-y1+2)]
    par_tuple = []
    for kernels in [[(x[0],y[0]),(x[1],y[1])] for x in x_dims for y in y_dims]:
        CNN_dict   = {image_shape:{'maps':n_maps, 'kernels':kernels}}
        par_tuple += [(NN_weights(image_shape, CNN_dict, FCN_neurons, n_classes), kernels)]
    return sorted(par_tuple)[::-1]


def print_channels(sample, labels, col=1, reverse=True, composition='classes'):
    def getkey(item): return item[col] if col==0 else 0 if item[col]=='' else np.float(item[col])
    channel_dict= {301000:'dyee 120-180'       , 301003:'dyee 400-600'      , 301004:'dyee 600-800'       ,
                   301009:'dyee 1750-2000'     , 301010:'dyee 2000-2250'    , 301012:'dyee 2500-2750'     ,
                   301016:'dyee 4000-4500'     , 301017:'dyee 4500-5000'    , 301018:'dyee 5000'          ,
                   301535:'Z --> ee+y 10-35'   , 301536:'Z --> mumu+y 10-35', 301899:'Z --> ee+y 35-70'   ,
                   301900:'Z --> ee+y 70-140'  , 301901:'Z --> ee+y 140'    , 301902:'Z --> mumu+y 35-70' ,
                   301903:'Z --> mumu+y 70-140', 301904:'Z --> mumu+y 140'  , 361020:'dijet JZ0W'         ,
                   361021:'dijet JZ1W'         , 361022:'dijet JZ2W'        , 361023:'dijet JZ3W'         ,
                   361024:'dijet JZ4W'         , 361025:'dijet JZ5W'        , 361026:'dijet JZ6W'         ,
                   361027:'dijet JZ7W'         , 361028:'dijet JZ8W'        , 361029:'dijet JZ9W'         ,
                   361100:'W+ --> ev'          , 361101:'W+ --> muv'        , 361102:'W+ --> tauv'        ,
                   361103:'W- --> ev'          , 361104:'W- --> muv'        , 361105:'W- --> tauv'        ,
                   361106:'Z  --> ee'          , 361108:'Z  --> tautau'     , 361665:'dyee 10-60'         ,
                   410470:'ttbar nonhad'       , 410471:'ttbar allhad'      , 410644:'s top s-chan.'      ,
                   410645:'s top s-chan.'      , 410646:'s top Wt-chan.'    , 410647:'s top Wt-chan.'     ,
                   410658:'s top t-chan.'      , 410659:'s top t-chan.'     , 423099:'y+jets 8-17'        ,
                   423100:'y+jets 17-35'       , 423101:'y+jets 35-50'      , 423102:'y+jets 50-70'       ,
                   423103:'y+jets 70-140'      , 423104:'y+jets 140-280'    , 423105:'y+jets 280-500'     ,
                   423106:'y+jets 500-800'     , 423107:'y+jets 800-1000'   , 423108:'y+jets 1000-1500'   ,
                   423109:'y+jets 1500-2000'   , 423110:'y+jets 2000-2500'  , 423111:'y+jets 2500-3000'   ,
                   423112:'y+jets 3000'        , 423200:'direct:Jpsie3e3'   , 423201:'direct:Jpsie3e8'    ,
                   423202:'direct:Jpsie3e13'   , 423211:'np:bb --> Jpsie3e8', 423212:'np:bb --> Jpsie3e13',
                   423300:'JF17'               , 423301:'JF23'              , 423302:'JF35', 423303:'JF50'}
    channels = sample['mcChannelNumber']; classes = np.unique(labels); n_e = len(labels)
    channel_dict.update({**{n:'unknown'  for n in set(channels)-set(channel_dict.keys())}, 0:'Data LF'})
    channel_num = {n:np.sum(channels==n) for n in set(channels)}
    if   composition == 'electrons':
        class_ratios = {n:[np.sum(channels[labels==m]==n)/n_e               for m in classes] for n in set(channels)}
    elif composition == 'channels':
        class_ratios = {n:[np.sum(channels[labels==m]==n)/channel_num[n]    for m in classes] for n in set(channels)}
    elif composition == 'classes':
        class_ratios = {n:[np.sum(channels[labels==m]==n)/np.sum(labels==m) for m in classes] for n in set(channels)}
    class_ratios = {n:['' if m==0 else format(1e2*m,'.1e').replace('e-0','e-0') if np.round(1e4*m)==0
                       else format(1e2*m,'.2f') for m in val] for n,val in class_ratios.items()}
    channel_rows = sorted([[channel_dict[n], format(100*channel_num[n]/n_e,'.2f'), str(n)] + class_ratios[n]
                           for n in class_ratios], key=getkey)
    class_dict = {0:'Prompt', 1:'CF', 2:'PC', 3:'HF', 4:'LF' if len(classes)<=5 else 'LF e/ɣ', 5:'LF Had'}
    headers = ['Process', '%  ', 'Channel'] + [format(class_dict[n],'>6s')+' (%)' for n in classes]
    print(tabulate(channel_rows[::-1] if reverse else channel_rows, headers=headers, tablefmt='psql', floatfmt='.2f',
                   disable_numparse=True, colalign=['left','right','right']+['right' for n in classes])); sys.exit()


def class_channels(sample, labels, output_dir, col=1, reverse=True, composition='classes'):
    def getkey(item): return item[col] if col==0 else 0 if item[col]=='' else np.float(item[col])
    channel_dict = {'JF17-35-50':[423300, 423302, 423303],
                    'ttbar'     :[410470],
                    'WZ'        :[361100, 361102, 361103, 361105, 361106, 361108],
                    'Drell-Yan' :[301000, 301003, 301004, 301009, 301010, 301012, 301016, 301017, 301018, 361665],
                    'gamma+jet' :[423100, 423101, 423102, 423103, 423107, 423108, 423109, 423110, 423111, 423112]}
    channels = sample['mcChannelNumber']; classes = np.unique(labels); n_e = len(labels)
    channel_dict = {key:set(np.unique(channels))&set(val) for key,val in channel_dict.items()}
    channel_num = {key:np.sum(np.logical_or.reduce([channels==n for n in val])) for key,val in channel_dict.items()}
    if   composition == 'electrons':
        class_ratios = {key:[np.sum((np.logical_or.reduce([channels==n for n in val]))&(labels==m))/n_e
                             for m in classes] for key,val in channel_dict.items()}
    elif composition == 'channels':
        class_ratios = {key:[np.sum((np.logical_or.reduce([channels==n for n in val]))&(labels==m))/channel_num[key]
                             for m in classes] for key,val in channel_dict.items()}
    elif composition == 'classes':
        class_ratios = {key:[np.sum((np.logical_or.reduce([channels==n for n in val]))&(labels==m))/np.sum(labels==m)
                             for m in classes] for key,val in channel_dict.items()}
        plot_classes(sample, labels, channel_dict, class_ratios, output_dir); print()
    class_ratios = {key:['' if m==0 else format(1e2*m,'.1e').replace('e-0','e-0') if np.round(1e4*m)==0
                       else format(1e2*m,'.2f') for m in val] for key,val in class_ratios.items()}
    channel_rows = sorted([[key, format(100*channel_num[key]/n_e,'.2f')] + val
                           for key,val in class_ratios.items()], key=getkey)
    class_dict = {0:'Prompt', 1:'CF', 2:'PC', 3:'HF', 4:'LF' if len(classes)<=5 else 'LF e/ɣ', 5:'LF Had'}
    headers = ['Processes', '%  '] + [format(class_dict[n],'>6s')+' (%)' for n in classes]
    print(tabulate(channel_rows[::-1] if reverse else channel_rows, headers=headers, tablefmt='psql', floatfmt='.2f',
                   disable_numparse=True, colalign=['left','right']+['right' for n in classes]))
    print(); sys.exit()


def sample_analysis(sample, labels, scalars, scaler_file, generator, output_dir):
    if generator == 'ON': sys.exit()
    #verify_sample(sample); sys.exit()
    #sample_histograms(sample, labels, sample, labels, None, output_dir)#; sys.exit()
    # MC CHANNELS
    print_channels(sample, labels)
    #class_channels(sample, labels, output_dir)
    # DISTRIBUTION HEATMAPS
    #from plots_DG import plot_heatmaps
    #plot_heatmaps(sample, labels, output_dir); sys.exit()
    # CALORIMETER IMAGES
    from plots_DG import cal_images
    layers  = [ 'em_barrel_Lr0', 'em_barrel_Lr1_fine',   'em_barrel_Lr2',   'em_barrel_Lr3',
               #                  'tile_gap_Lr1'      ,
               # 'em_endcap_Lr0', 'em_endcap_Lr1_fine',   'em_endcap_Lr2',   'em_endcap_Lr3',
               #'lar_endcap_Lr0', 'lar_endcap_Lr1'    ,  'lar_endcap_Lr2',  'lar_endcap_Lr3',
                                 'tile_barrel_Lr1'   , 'tile_barrel_Lr2', 'tile_barrel_Lr3'
               ]
    cal_images(sample, labels, layers, output_dir, mode='mean', scale='free', soft=False)


def feature_removal(scalars, images, groups, index):
    if   index <= 0:
        return scalars, images, 'none'
    elif index >  len(scalars+images+groups):
        sys.exit()
    elif index <= len(scalars+images):
        #removed_feature = (scalars+images)[index-1]
        removed_feature = dict(zip(np.arange(1, len(scalars+images)+1), scalars+images))[index]
        scalars_list    = list(set(scalars) - set([removed_feature]))
        images_list     = list(set(images ) - set([removed_feature]))
    elif index  > len(scalars+images):
        removed_feature = groups[index-1-len(scalars+images)]
        scalars_list    = list(set(scalars) - set(removed_feature))
        images_list     = list(set(images ) - set(removed_feature))
        removed_feature = 'group_'+str(index-len(scalars+images))
    scalars = [scalar for scalar in scalars if scalar in scalars_list]
    images  = [ image for  image in  images if  image in  images_list]
    return scalars, images, removed_feature


def feature_ranking(output_dir, results_out, scalars, images, groups):
    data_dict = {}
    with open(results_out,'rb') as file_data:
        try:
            while True: data_dict.update(pickle.load(file_data))
        except EOFError: pass
    try: pickle.dump(data_dict, open(results_out,'wb'))
    except IOError: print('FILE ACCESS CONFLICT IN FEATURE RANKING --> SKIPPING FILE ACCESS\n')
    # SECTION TO MODIFY
    #from importance import ranking_plot
    #ranking_plot(data_dict, output_dir, 'put title here', images, scalars, groups)
    print('BACKGROUND REJECTION DICTIONARY:')
    for key in data_dict: print(format(key,'30s'), data_dict[key])




#################################################################################
#####    presampler.py functions    #############################################
#################################################################################


def presample(h5_file, output_dir, batch_size, sum_e, images, tracks, scalars, integers, file_key, n_tasks, index):
    idx = index*batch_size, (index+1)*batch_size
    with h5py.File(h5_file, 'r') as data:
        images  = list(set(images  ) & set(data[file_key]))
        tracks  = list(set(tracks  ) & set(data[file_key]))
        scalars = list(set(scalars ) & set(data[file_key]))
        int_val = list(set(integers) & set(data[file_key]))
        sample = {key:data[file_key][key][idx[0]:idx[1]] for key in images+tracks+scalars+int_val}
    for key in images: sample[key] = sample[key]/(sample['p_e'][:, np.newaxis, np.newaxis])
    for key in ['em_barrel_Lr1', 'em_endcap_Lr1']:
        try:
            if sample[key].shape[1:] != (7,11):
                sample[key+'_fine'] = sample[key]
        except KeyError:
            pass
    for key in images        : sample[key] = resize_images(sample[key])
    for key in images+scalars: sample[key] = np.float16(np.clip(sample[key],-5e4,5e4))
    try: sample['p_TruthType']   = sample.pop('p_truthType')
    except KeyError: pass
    try: sample['p_TruthOrigin'] = sample.pop('p_truthOrigin')
    except KeyError: pass
    #tracks_list = [np.expand_dims(get_tracks(sample, n, 50, ''        ), axis=0) for n in np.arange(batch_size)]
    #sample['tracks'] = np.concatenate(tracks_list)
    tracks_list = [np.expand_dims(get_tracks(sample, n, 10, 'p_'      ), axis=0) for n in np.arange(batch_size)]
    sample['p_tracks'] = np.concatenate(tracks_list)
    tracks_list = [np.expand_dims(get_tracks(sample, n, 50, 'p_', True), axis=0) for n in np.arange(batch_size)]
    tracks_list = np.concatenate(tracks_list)
    tracks_dict = {'p_mean_efrac'  :0 , 'p_mean_deta'   :1 , 'p_mean_dphi'   :2 , 'p_mean_d0'          :3 ,
                   'p_mean_z0'     :4 , 'p_mean_charge' :5 , 'p_mean_vertex' :6 , 'p_mean_chi2'        :7 ,
                   'p_mean_ndof'   :8 , 'p_mean_pixhits':9 , 'p_mean_scthits':10, 'p_mean_trthits'     :11,
                   'p_mean_sigmad0':12, 'p_qd0Sig'      :13, 'p_nTracks'     :14, 'p_sct_weight_charge':15}
    for key in tracks_dict:
        if np.any(tracks_list[:,tracks_dict[key]]!=0): sample[key] = tracks_list[:,tracks_dict[key]]
    for key in tracks + ['p_truth_E', 'p_truth_e']:
        try: sample.pop(key)
        except KeyError: pass
    index = utils.shuffle(np.arange(n_tasks), random_state=sum_e)[index%n_tasks]
    with h5py.File(output_dir+'/'+'e-ID_'+'{:=02}'.format(index)+'.h5', 'w' if sum_e==0 else 'a') as data:
        for key in sample:
            shape = (sum_e+batch_size,) + sample[key].shape[1:]
            if sum_e == 0:
                dtype = 'i4' if key in integers else 'f2'
                maxshape = (None,)+sample[key].shape[1:]
                chunks   = (2000,)+sample[key].shape[1:]
                data.create_dataset(key, shape, dtype=dtype, maxshape=maxshape, chunks=chunks, compression='lzf')
            else:
                data[key].resize(shape)
        for key in sample:
            data[key][sum_e:sum_e+batch_size,...] = utils.shuffle(sample[key], random_state=0)


def resize_images(images):
    if   images.shape[1:] == (56,11):
        images = [np.sum(images[:,8*n:8*n+8,:], axis=1)[:,np.newaxis,:] for n in range(7)]
        images = np.concatenate(images, axis=1)
    #elif images.shape[1:] != (7,11)
    #    energy_fine   = np.sum(images, axis=(1,2))
    #    images        = transform.resize(images, ((len(images),)+target_shape))
    #    energy_coarse = np.sum(images, axis=(1,2))
    #    energy_fine  [energy_coarse <= 1e-6] = 0.
    #    energy_coarse[energy_coarse <= 1e-6] = 1.
    #    images *= np.expand_dims(energy_fine/energy_coarse, axis=(1,2))
    return images


def get_tracks(sample, idx, max_tracks=20, p='p_', make_scalars=False):
    tracks_p    = np.cosh(sample[p+'tracks_eta'][idx]) * sample[p+'tracks_pt' ][idx]
    tracks_deta =         sample[p+'tracks_eta'][idx]  - sample[  'p_eta'     ][idx]
    tracks_dphi =         sample[p+'tracks_phi'][idx]  - sample[  'p_phi'     ][idx]
    tracks_d0   =         sample[p+'tracks_d0' ][idx]
    tracks_z0   =         sample[p+'tracks_z0' ][idx]
    tracks_dphi = np.where(tracks_dphi < -np.pi, tracks_dphi + 2*np.pi, tracks_dphi )
    tracks_dphi = np.where(tracks_dphi >  np.pi, tracks_dphi - 2*np.pi, tracks_dphi )
    tracks      = [tracks_p/sample['p_e'][idx], tracks_deta, tracks_dphi, tracks_d0, tracks_z0]
    p_tracks    = ['p_tracks_charge' , 'p_tracks_vertex' , 'p_tracks_chi2'   , 'p_tracks_ndof',
                   'p_tracks_pixhits', 'p_tracks_scthits', 'p_tracks_trthits', 'p_tracks_sigmad0']
    if p == 'p_':
        for key in p_tracks:
            try: tracks += [sample[key][idx]]
            except KeyError: tracks += [np.zeros(sample['p_tracks_charge'][idx].shape)]
    tracks      = np.float16(np.vstack(tracks).T)
    tracks      = tracks[np.isfinite(np.sum(abs(tracks), axis=1))][:max_tracks,:]
    #tracks      = np.float16(np.clip(np.vstack(tracks).T,-5e4,5e4))[:max_tracks,:]
    if p == 'p_' and make_scalars:
        tracks_means = np.mean(tracks,axis=0) if len(tracks)!=0 else tracks.shape[1]*[0]
        qd0Sig       = sample['p_charge'][idx] * sample['p_d0'][idx] / sample['p_sigmad0'][idx]
        if np.any(sample['p_tracks_scthits'][idx]!=0):
            sct_weight_charge  = sample['p_tracks_charge'][idx] @     sample['p_tracks_scthits'][idx]
            sct_weight_charge *= sample['p_charge'       ][idx] / sum(sample['p_tracks_scthits'][idx])
        else:
            sct_weight_charge = 0
        return np.concatenate([tracks_means, np.array([qd0Sig, len(tracks), sct_weight_charge])])
    else:
        return np.vstack([tracks, np.zeros((max(0, max_tracks-len(tracks)), tracks.shape[1]))])


def merge_presamples(output_dir, output_file):
    h5_files = [h5_file for h5_file in os.listdir(output_dir) if 'e-ID_' in h5_file and '.h5' in h5_file]
    #h5_files = [h5_file for h5_file in os.listdir(output_dir) if 'myTag' in h5_file and '.h5' in h5_file]
    if len(h5_files) == 0: sys.exit()
    np.random.seed(0); np.random.shuffle(h5_files)
    idx = np.cumsum([len(h5py.File(output_dir+'/'+h5_file, 'r')['eventNumber']) for h5_file in h5_files])
    os.rename(output_dir+'/'+h5_files[0], output_dir+'/'+output_file)
    dataset = h5py.File(output_dir+'/'+output_file, 'a')
    GB_size = len(h5_files)*sum([np.float16(dataset[key]).nbytes for key in dataset])/(1024)**2/1e3
    print('MERGING DATA FILES (', '\b{:.1f}'.format(GB_size),'GB) IN:', end=' ')
    print('output/'+output_file, end=' .' if len(h5_files)>1 else '', flush=True); start_time = time.time()
    for key in dataset: dataset[key].resize((idx[-1],) + dataset[key].shape[1:])
    for h5_file in h5_files[1:]:
        data  = h5py.File(output_dir+'/'+h5_file, 'r')
        index = h5_files.index(h5_file)
        for key in dataset:
            if dataset[key].dtype != 'object':
                dataset[key][idx[index-1]:idx[index]] = data[key]
        data.close(); os.remove(output_dir+'/'+h5_file)
        print('.', end='', flush=True)
    print(' (', '\b'+format(time.time() - start_time,'.1f'), '\b'+' s) -->', idx[-1], 'ELECTRONS COLLECTED\n')


def get_idx(size, start_value=0, n_sets=5):
    n_sets   = min(size, n_sets)
    idx_list = [start_value + n*(size//n_sets) for n in np.arange(n_sets)] + [start_value+size]
    return list(zip(idx_list[:-1], idx_list[1:]))


def mix_datafiles(input_path='', input_dir='', temp_dir='temp_dir', n_tasks=10, replace_LF=False):
    data_files = get_dataset(input_path, input_dir) ; n_files = len(data_files)
    #for data_file in  data_files: print(data_file)
    #sys.exit()
    if replace_LF:
        LF_path  = '/nvme1/atlas/godin/e-ID_data/LFdata/LFdata_17-18'
        LF_files = sorted([LF_path+'/'+h5_file for h5_file in os.listdir(LF_path) if 'e-ID_' in h5_file])
        #for index in range(len(data_files)): print(data_files[index], LF_files[index])
        #sys.exit()
    else:
        LF_files = None
    output_dir = data_files[0].split(input_dir)[0] + temp_dir
    if not os.path.isdir(output_dir): os.mkdir(output_dir)
    for idx in np.split(utils.shuffle(np.arange(n_files)), np.arange(n_tasks,n_files,n_tasks)):
        arguments = [(data_files[index], LF_files, index, output_dir) for index in idx]
        processes = [mp.Process(target=file_mixing, args=arg) for arg in arguments]
        for job in processes: job.start()
        for job in processes: job.join()
def file_mixing(h5_file, LF_files, index, output_dir):
    features = utils.shuffle(list(h5py.File(h5_file,'r')), random_state=index)
    MC_data  = h5py.File(h5_file,'r')
    if LF_files is not None:
        # Light flavor indices in MC file
        iffTruth  = MC_data['p_iffTruth' ][:]
        TruthType = MC_data['p_TruthType'][:]
        MC_criteria = np.logical_or.reduce([TruthType==4, TruthType==16, TruthType==17])
        MC_criteria = np.logical_and(MC_criteria, iffTruth==10)
        MC_idx  = np.where(MC_criteria)[0]
        LF_data = h5py.File(LF_files[index],'r')
        source_size = len(list(LF_data.values())[0])
        target_size = np.sum(MC_criteria)
        # Light flavor indices from data file
        rng = np.random.default_rng()
        LF_idx = rng.choice(source_size, target_size, replace=source_size<target_size)
    for key in features:
        attribute = 'w' if key==features[0] else 'a'
        data_in  = MC_data[key][:]
        data_out = h5py.File(output_dir+'/'+h5_file.split('/')[-1], attribute)
        if LF_files is not None:
            # Replacing light flavor MC
            data_in[MC_idx] = np.take(LF_data[key], LF_idx, axis=0)
            # Labelling light flavor data
            if key == 'p_iffTruth' : data_in = np.where(MC_criteria, 10, data_in )
            if key == 'p_TruthType': data_in = np.where(MC_criteria,  1, data_in )
        dtype  = np.int32 if data_in.dtype=='int32' else np.float16
        chunks = (2000,) + data_in.shape[1:]
        data_out.create_dataset(key, data_in.shape, dtype=dtype, compression='lzf', chunks=chunks)
        print( 'Mixing file', h5_file.split('/')[-2]+'/'+h5_file.split('/')[-1], 'with feature', key )
        if LF_files is not None: data_out[key][:] =               data_in[:]
        else                   : data_out[key][:] = utils.shuffle(data_in[:], random_state=index)


def mix_presamples(input_path, output_dir, temp_dir='temp_dir', n_files=20, n_tasks=5):
    data_files = get_dataset(input_path, temp_dir)
    #for data_file in data_files: print(data_file)
    #sys.exit()
    output_dir = data_files[0].split(temp_dir)[0] + output_dir
    if not os.path.isdir(output_dir): os.mkdir(output_dir)
    n_e      = [len(h5py.File(h5_file,'r')['eventNumber']) for h5_file in data_files]
    idx_list = [get_idx(n, n_sets=n_files) for n in n_e]
    file_idx = list(utils.shuffle(np.arange(n_files), random_state=0))
    for idx in np.split(file_idx, np.arange(n_tasks, n_files, n_tasks)):
        start_time = time.time()
        arguments = [(data_files, idx_list, file_idx, out_idx, output_dir) for out_idx in idx]
        processes = [mp.Process(target=mix_samples, args=arg) for arg in arguments]
        for job in processes: job.start()
        for job in processes: job.join()
        print('run time:', format(time.time() - start_time, '2.1f'), '\b'+' s\n')
    import shutil; shutil.rmtree( data_files[0].split(temp_dir)[0] + temp_dir )
def mix_samples(data_files, idx_list, file_idx, out_idx, output_dir):
    features = list(set().union(*[h5py.File(h5_file,'r').keys() for h5_file in data_files]))
    features = list(set(features)-{'p_passWVeto','p_trigMatches','p_passZVeto','p_trigMatches_pTbin','p_met'})
    features = utils.shuffle(features, random_state=out_idx)
    for key in features:
        sample_list = []
        for in_idx in utils.shuffle(np.arange(len(data_files)), random_state=out_idx):
            idx = idx_list[in_idx][out_idx]
            try:
                sample_list += [h5py.File(data_files[in_idx],'r')[key][idx[0]:idx[1]]]
            except KeyError:
                if 'fine' in key: sample_list += [np.zeros((idx[1]-idx[0],)+(56,11), dtype=np.int8)]
                else            : sample_list += [np.zeros((idx[1]-idx[0],)+( 7,11), dtype=np.int8)]
        sample = np.concatenate(sample_list)
        file_name = 'e-ID_'+'{:=02}'.format(file_idx.index(out_idx))+'.h5'
        attribute = 'w' if key==features[0] else 'a'
        data = h5py.File(output_dir+'/'+file_name, attribute, rdcc_nbytes=20*1024**3, rdcc_nslots=10000019)
        shape    = (len(sample),) + sample.shape[1:]
        maxshape = (None,)+sample.shape[1:]
        dtype    = np.int32 if sample.dtype=='int32' else np.float16
        chunks   = (2000,)+sample.shape[1:]
        data.create_dataset(key, shape, maxshape=maxshape, dtype=dtype, compression='lzf', chunks=chunks)
        data[key][:] = utils.shuffle(sample, random_state=0)
        print( file_idx.index(out_idx), key)




#################################################################################
#####    Kazuya functions    ####################################################
#################################################################################


def find_bin(array,binning):

    binarized_bin_indices=list()
    for i in range(len(binning)-1):
        binarized_bin_indices.append( ((binning[i]<array) & (array<=binning[i+1])).astype(float) )
        #tmp_array = (binning[i]<array) & (array<binning[i+1])
        #print(tmp_array)
        pass

    #print(np.shape(binarized_bin_indices[0]))

    return binarized_bin_indices
#def find_bin(element,binning):
#
#    binNum=-1 # underflow and overflow
#    for i in range(len(binning)-1):
#        if binning[i]<element and element<binning[i+1]: binNum=i
#        pass
#
#    return binNum

def get_bin_indices(p_var,boundaries):
    bin_indices=list()
    #print("hi=",boundaries[0],np.where( p_var<boundaries[0] )[0])
    bin_indices.append (np.where( p_var<=boundaries[0] )[0])
    for idx in range(len(boundaries)-1):
        #print("lo, hi=",boundaries[idx],":",boundaries[idx+1])
        bin_indices.append (np.where( (boundaries[idx]<p_var) & (p_var<=boundaries[idx+1]) )[0])
        #bin_indices.append (np.where( (boundaries[idx]<=p_var) & (p_var<boundaries[idx+1]) & (isnan(p_var)) )[0])
        pass
    #print("lo=",boundaries[len(boundaries)-1],np.where( boundaries[len(boundaries)-1]<p_var )[0])
    bin_indices.append (np.where( boundaries[len(boundaries)-1]<p_var )[0])
    #print(len(bin_indices),len(boundaries))

    tmp_idx=0
    total=0
    #total=len(bin_indices[0])
    #print("hi=",boundaries[0],bin_indices[0],len(bin_indices[0]),total)

    debug=False
    for bin_idx in bin_indices:
        total+=len(bin_idx)

        if debug:
            if tmp_idx==0:
                print("hi=",boundaries[tmp_idx],bin_idx,len(bin_idx),total)
            elif tmp_idx==len(bin_indices)-1:
                print("lo=",boundaries[tmp_idx-1],bin_idx,len(bin_idx),total)
            else:
                print("lo,hi=[",boundaries[tmp_idx-1],",",boundaries[tmp_idx],"]",bin_idx,len(bin_idx),total)
                pass
            pass

        tmp_idx+=1
        pass
    total+=len(bin_indices[-1])
    #print("lo=",boundaries[-1],bin_indices[-1],len(bin_indices[-1]),total)

    return bin_indices

def getMaxContents(binContents):

    maxContents = np.full(len(binContents[0]),-1.)
    for i_bin in range(len(binContents[0])):
        for i in range(len(binContents)):
            if binContents[i][i_bin] > maxContents[i_bin]: maxContents[i_bin] = binContents[i][i_bin]
            pass
        pass
    #print("maxContens=",maxContents)

    return maxContents

#def generate_weights(train_data,train_labels,nClass,weight_type='none',ref_var='pt',output_dir='outputs/'):
def sample_weights(train_data,train_labels,nClass,weight_type,output_dir='outputs/',ref_var='pt'):
    if weight_type=="none": return None

    print("-------------------------------")
    print("generate_weights: sample weight mode \"",weight_type,"\" designated. Generating weights.",)
    print("-------------------------------\n")

    binning=[0,10,20,30,40,60,80,100,130,180,250,500]
    labels=['sig','bkg']
    colors=['blue','red']
    binContents=[0,0]
    if nClass==6:
        #below 2b implemented
        labels=['sig','chf','conv','hf','eg','lf']
        colors=['blue','orange','green','red','purple','brown']
        binContents=[0,0,0,0,0,0]
        pass

    variable=list()                          #only for specific label
    variable_array = train_data['p_et_calo'] #entire set
    if   ref_var=='eta'  : variable_array = train_data['p_eta']
    #elif ref_var=='pteta': variable_array = train_data['p_eta']

    for i_class in range(nClass):
        variable.append( variable_array[ train_labels==i_class ] )
        (binContents[i_class],bins,patches)=plt.hist(variable[i_class],bins=binning,weights=np.full(len(variable[i_class]),1/len(variable[i_class])),label=labels[i_class],histtype='step',facecolor=colors[i_class])
        #(binContents[i_class],bins,patches)=plt.hist(variable[i_class],bins=binning,weights=np.full(len(variable[i_class]),1/len(train_labels)),label=labels[i_class],histtype='step',facecolor=colors[i_class])
        pass

        if nClass>2: plt.yscale("log")
        plt.savefig(output_dir+'/'+ref_var+"_bfrReweighting.png")
    plt.clf() #clear figure

    weights=list() #KM: currently implemented for the 2-class case only
    if weight_type=="flattening":
        for i in range(nClass): weights.append(np.average(binContents[i])/binContents[i] )
    elif weight_type=="match2max": #shaping to whichever that has max in the corresponding bin
        #for i in range(nClass): print("bincontens[",i,"]=",binContents[i])
        maxContents = getMaxContents(binContents)#print(maxContents)
        for i in range(nClass): weights.append( maxContents/binContents[i] )
    elif weight_type=="match2b": #shaping sig to match the bkg, using pt,or any other designated variable
        for i in range(nClass-1): weights.append(binContents[nClass-1]/binContents[i])
        weights.append(np.ones(len(binContents[5])))
    elif weight_type=="match2s": #shaping bkg to match the sig, using pt,or any other designated variable
        weights.append(np.ones(len(binContents[0])))
        for i in range (1, nClass): weights.append(binContents[0]/binContents[i])
        pass

    #KM: to replce inf with 0
    for i in range(nClass): weights[i]=np.where(weights[i]==np.inf,0,weights[i]) #np.where(array1==0, 1, array1)

    debug=0
    if debug:
        tmp_i=0
        for weight in weights:
            print("weights[",labels[tmp_i],"]=",weight)
            tmp_i+=1
        #print(weights[0])
        #print(weights[1])
        pass

    #KM: Generates weights for all events
    #    This is not very efficient, to be improved

    #final_weights*=weights[train_labels][1]

    class_weight=list()
    for i in range(nClass): class_weight.append( np.full(len(variable_array),0,dtype=float) )
    final_weights= np.full(len(variable_array),0,dtype=float)
    #sig_weight=np.full(len(variable_array),0,dtype=float)
    #bkg_weight=np.full(len(variable_array),0,dtype=float)

    #To produce vectors of 0 or 1 for given pt ranges
    bin_indices0or1=find_bin(variable_array,binning)
    tmp_i=0 # pt bin index
    for vec01 in bin_indices0or1:
        #KM: this line is the most important to calculate the weights for al events
        for i in range(nClass): class_weight[i] += (vec01 * (train_labels==i) )* weights[i][tmp_i]
        #sig_weight += (vec01 * (train_labels==0) )* weights[0][tmp_i]
        #bkg_weight += (vec01 * (train_labels==1) )* weights[1][tmp_i]
        tmp_i+=1
        pass

    if debug:
        print()
        #print(sig_weight,"\n", bkg_weight)
        tmp_i=0
        for i in range(nClass):
            print("class_weight[",tmp_i,"]=",class_weight[i])
            tmp_i+=1
            pass
        #print("final_weights=",final_weights) #print(final_weights,final_weights.all()==1) # w
        print("train_labels=",train_labels)
        pass

    for i in range(nClass): final_weights+=class_weight[i]

    if debug:
        print("variable_array=",variable_array)
        print(final_weights, len(final_weights), "any element is zero?",final_weights.any()==0)
        pass

    #KM: below only for plotting
    for i_class in range(nClass):
        plt.hist(variable[i_class],bins=binning,weights=final_weights[ train_labels==i_class ],label=labels[i_class],histtype='step',facecolor=colors[i_class])
        #weights = final_weights[ train_labels==i_class ]/len(train_labels)
        #plt.hist(variable[i_class],bins=binning, weights=weights, label=labels[i_class],histtype='step',facecolor=colors[i_class])
        pass
    if nClass>2: plt.yscale("log")
    plt.savefig(output_dir+'/'+ref_var+"_aftReweighting.png")
    plt.clf() #clear plot

    return final_weights
