import tensorflow as tf, numpy as np, h5py, os, sys
from sklearn.metrics import confusion_matrix
from sklearn.utils   import shuffle
from tabulate        import tabulate
from skimage         import transform


def make_data(data_file, dict_var, indices, float16=True, upscale=False, denormalize=False):
    data, list_var = h5py.File(data_file, 'r'), np.sum(list(dict_var.values()))
    images, tracks = dict_var['images'], dict_var['tracks']
    if float16: sample = dict([key,            data[key][indices[0]:indices[1]]]  for key in list_var)
    else:       sample = dict([key, np.float32(data[key][indices[0]:indices[1]])] for key in list_var)
    if denormalize:
        for n in images: sample[n]        = sample[n]        * sample['p_e'][:, np.newaxis, np.newaxis]
        for n in tracks: sample[n][:,:,0] = sample[n][:,:,0] * sample['p_e'][:, np.newaxis]
    if upscale:
        for n in images: sample[n]        = resize_images(np.float32(sample[n]), target_shape=(56,11))
    return sample


def make_labels(sample, n_classes):
    labels = sample['p_iffTruth']
    if n_classes == 2: # iffTruth based with iff=2,3 signal electrons
        labels = np.where(labels<=1                          , -1, labels)
        labels = np.where(labels>=4                          ,  1, labels)
        return   np.where(np.logical_or(labels==2, labels==3),  0, labels)
    #if n_classes == 2: # TruthType based with type 2 and 4 signal electrons
    #    labels = sample['p_TruthType']
    #    return   np.where(np.logical_or(labels==2, labels==4),  0, 1     )
    #if n_classes == 2: # TruthType based without type 4 signal electrons
    #    labels = sample['p_TruthType']
    #    labels = np.where(np.logical_and(labels!=2, labels!=4), 1, labels)
    #    labels = np.where(labels==2,  0, labels)
    #    return   np.where(labels==4, -1, labels)
    elif n_classes == 5:
        labels = np.where(np.logical_or(labels<=1, labels==4), -1, labels)
        labels = np.where(np.logical_or(labels==6, labels==7), -1, labels)
        labels = np.where(labels==2                          ,  0, labels)
        labels = np.where(labels==3                          ,  1, labels)
        labels = np.where(labels==5                          ,  2, labels)
        labels = np.where(np.logical_or(labels==8, labels==9),  3, labels)
        return   np.where(labels==10                         ,  4, labels)
    elif n_classes == 6:
        labels = np.where(np.logical_or(labels<=1, labels==4),                   -1, labels)
        labels = np.where(np.logical_or(labels==6, labels==7),                   -1, labels)
        labels = np.where(labels==2                          ,                    0, labels)
        labels = np.where(labels==3                          ,                    1, labels)
        labels = np.where(labels==5                          ,                    2, labels)
        labels = np.where(np.logical_or(labels==8, labels==9),                    3, labels)
        labels = np.where(np.logical_and(labels==10, sample['p_TruthType']==4 ),  4, labels)
        labels = np.where(np.logical_and(labels==10, sample['p_TruthType']==17),  5, labels)
        return   np.where(labels==10                                           , -1, labels)
    elif n_classes == 9:
        labels = np.where(labels== 9, 4, labels)
        return   np.where(labels==10, 6, labels)
    else: print('\nCLASSIFIER: classes not supported -> exiting program\n') ; sys.exit()


def filter_sample(sample, labels):
    label_rows  = np.where(labels!=-1)[0]
    n_conserved = 100*len(label_rows)/len(labels)
    for key in sample: sample[key] = np.take(sample[key], label_rows, axis=0)
    print('CLASSIFIER: filtering sample ->', format(n_conserved, '.2f'),'% conserved\n')
    return sample, np.take(labels, label_rows)


def balance_sample(sample, labels, n_classes):
    class_size = int(len(labels)/n_classes)
    class_rows = [np.where(labels==m)[0] for m in np.arange(n_classes)]
    class_rows = [np.random.choice(class_rows[m], class_size, replace=len(class_rows[m])<class_size)
                  for m in np.arange(n_classes)]
    class_rows = np.concatenate(class_rows) ; np.random.shuffle(class_rows)
    for key in sample: sample[key] = np.take(sample[key], class_rows, axis=0)
    return sample, np.take(labels, class_rows)


class Batch_Generator(tf.keras.utils.Sequence):
    def __init__(self, file_name, n_classes, train_features, all_features, indices, batch_size):
        self.file_name  = file_name  ; self.train_features = train_features
        self.indices    = indices    ; self.all_features   = all_features
        self.batch_size = batch_size ; self.n_classes      = n_classes
    def __len__(self):
        "number of batches per epoch"
        return int(self.indices.size/self.batch_size)
    def __getitem__(self, index):
        data   = generator_sample(self.file_name, self.all_features, self.indices, self.batch_size, index)
        labels = make_labels(data, self.n_classes)
        data   = [np.float32(data[key]) for key in np.sum(list(self.train_features.values()))]
        return data, labels


def show_matrix(train_labels, test_labels, test_prob=[]):
    if test_prob == []: test_pred = test_labels
    else:               test_pred = np.argmax(test_prob, axis=1)
    matrix      = confusion_matrix(test_labels, test_pred)
    matrix      = 100*matrix.T/matrix.sum(axis=1)
    n_classes   = len(matrix)
    test_sizes  = [100*np.sum( test_labels==n)/len( test_labels) for n in np.arange(n_classes)]
    train_sizes = [100*np.sum(train_labels==n)/len(train_labels) for n in np.arange(n_classes)]
    classes     = ['CLASS '+str(n) for n in np.arange(n_classes)]
    if test_prob == []:
        print('+--------------------------------------+')
        print('| CLASS DISTRIBUTIONS                  |')
        headers = ['CLASS #', 'TRAIN (%)', 'TEST (%)']
        table   = zip(classes, train_sizes, test_sizes)
    else:
        if n_classes > 2:
            headers = ['CLASS #', 'TRAIN', 'TEST'] + classes
            table   = [classes] + [train_sizes] + [test_sizes] + matrix.T.tolist()
            table   = list(map(list, zip(*table)))
            print('\n+'+30*'-'+'+'+35*'-'+12*(n_classes-3)*'-'+'+\n', '\b| CLASS DISTRIBUTIONS (%)',
                  '    ', '| TEST SAMPLE PREDICTIONS (%)       '+12*(n_classes-3)*' '+ '|')
        else:
            headers = ['CLASS #', 'TRAIN (%)', 'TEST (%)', 'ACC. (%)']
            table   = zip(classes, train_sizes, test_sizes, matrix.diagonal())
            print('\n+---------------------------------------------------+')
            print(  '| CLASS DISTRIBUTIONS AND ACCURACIES                |')
    print(tabulate(table, headers=headers, tablefmt='psql', floatfmt=".2f"))


def make_samples(h5_file, output_path, batch_size, sum_e, images, tracks, scalars, int_var, index):
    idx_1, idx_2 = index*batch_size, (index+1)*batch_size
    data         = h5py.File(h5_file, 'r')
    energy       =                data['train']['p_e'][idx_1:idx_2][:, np.newaxis, np.newaxis        ]
    sample_list  = [resize_images(data['train'][ key ][idx_1:idx_2])/energy for key in images        ]
    sample_list += [              data['train'][ key ][idx_1:idx_2]         for key in tracks+scalars]
    sample_dict  = dict(zip(images+tracks+scalars, sample_list))
    sample_dict.update({'em_barrel_Lr1_fine':data['train']['em_barrel_Lr1'][idx_1:idx_2]/energy})
    tracks_list  = [np.expand_dims(get_tracks(sample_dict, e), axis=0) for e in np.arange(batch_size)]
    sample_dict.update({'tracks':np.concatenate(tracks_list), 'true_m':get_truth_m(sample_dict)})
    for wp in ['p_LHTight', 'p_LHMedium', 'p_LHLoose']: sample_dict[wp] = get_LLH(sample_dict, wp)
    for var in tracks + ['p_truth_E', 'p_LHValue']: sample_dict.pop(var)
    # For shuffling (to use next time)
    #for key in sample_dict.keys(): sample_dict[key] = shuffle(sample_dict[key], random_state=0)
    data = h5py.File(output_path+'temp_'+'{:=02}'.format(index)+'.h5', 'w' if sum_e==0 else 'a')
    for key in sample_dict.keys():
        shape = (sum_e+batch_size,) + sample_dict[key].shape[1:]
        if sum_e == 0:
            maxshape =  (None,) + sample_dict[key].shape[1:]
            dtype    = 'i4' if key in int_var else 'f4' if key=='tracks' else 'f2'
            data.create_dataset(key, shape, dtype=dtype, maxshape=maxshape, chunks=shape)
        else:
            data[key].resize(shape)
    for key in sample_dict.keys(): data[key][sum_e:sum_e+batch_size,...] = sample_dict[key]


def resize_images(images_array, target_shape=(7,11)):
    if images_array.shape[1:] == target_shape: return images_array
    else: return transform.resize(images_array, ( (len(images_array),) + target_shape))


def get_tracks(sample, idx, max_tracks=15):
    tracks_p    = np.cosh(sample['tracks_eta'][idx]) * sample['tracks_pt' ][idx]
    tracks_deta =     abs(sample['tracks_eta'][idx]  - sample['p_eta'     ][idx])
    tracks_dphi =         sample['p_phi'     ][idx]  - sample['tracks_phi'][idx]
    tracks_d0   =         sample['tracks_d0' ][idx]
    tracks      = np.vstack([tracks_p/sample['p_e'][idx], tracks_deta, tracks_dphi, tracks_d0]).T
    numbers     = list(set(np.arange(len(tracks))) - set(np.where(np.isfinite(tracks)==False)[0]))
    tracks      = np.take(tracks, numbers, axis=0)[:max_tracks,:]
    return        np.vstack([tracks, np.zeros((max(0, max_tracks-len(tracks)), 4))])


def get_LLH(sample, wp):
    llh =  np.where( sample[wp] == 0,                         2, 0   )
    return np.where( (llh == 2) & (sample['p_LHValue'] < -1), 1, llh )


def get_truth_m(sample, new=True, m_e=0.511, max_eta=4.9):
    truth_eta = np.vectorize(min)(abs(sample['p_truth_eta']), max_eta)
    truth_s   = sample["p_truth_E"]**2 - (sample['p_truth_pt']*np.cosh(truth_eta))**2
    if new: return np.where(truth_eta == max_eta, -1, np.sqrt(np.vectorize(max)(m_e**2, truth_s)))
    else:   return np.where(truth_eta == max_eta, -1, np.sign(truth_s)*np.sqrt(abs(truth_s)) )


def merge_samples(n_e, n_files, output_path, output_file):
    temp_files = sorted([h5_file for h5_file in os.listdir(output_path) if 'temp' in h5_file])
    # For shuffling (to use next time)
    #temp_files = [h5_file for h5_file in os.listdir(output_path) if 'temp' in h5_file]
    os.rename(output_path+temp_files[0], output_path+output_file)
    dataset    = h5py.File(output_path+output_file, 'a')
    MB_size    = n_files*sum([np.float16(dataset[key]).nbytes for key in dataset.keys()])/1e6
    print('Merging temporary files (', '\b{:.0f}'.format(MB_size),'MB) into:', end=' ')
    print('output/'+output_file, end=' .', flush=True)
    for key in dataset.keys(): dataset[key].resize((n_e*n_files,) + dataset[key].shape[1:])
    for h5_file in temp_files[1:]:
        data  = h5py.File(output_path+h5_file, 'r')
        index = temp_files.index(h5_file)
        for key in dataset.keys(): dataset[key][index*n_e:(index+1)*n_e] = data[key]
        data.close() ; os.remove(output_path+h5_file)
        print('.', end='', flush=True)


def check_sample(sample):
    bad_values = [np.sum(np.isfinite(sample[key])==False) for key in sample.keys()]
    print('CLASSIFIER:', sum(bad_values), 'found in sample')
