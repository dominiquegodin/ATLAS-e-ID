# IMPORT PACKAGES AND FUNCTIONS
import tensorflow as tf
import numpy      as np
import os, sys, h5py, pickle, itertools
from   argparse  import ArgumentParser
from   tabulate  import tabulate
from   utils     import get_dataset, validation, make_sample, merge_samples, sample_composition
from   utils     import compo_matrix, get_sample_weights, get_class_weight, gen_weights, Batch_Generator
from   utils     import cross_valid, valid_results, sample_analysis, feature_removal, feature_ranking
from   utils     import sample_histograms, fit_scaler, apply_scaler, fit_t_scaler, apply_t_scaler
from   plots_DG  import plot_history, plot_inputs
from   models    import callback, create_model


# PROGRAM ARGUMENTS
parser = ArgumentParser()
parser.add_argument( '--n_train'        , default =  1e6,  type = float )
parser.add_argument( '--n_eval'         , default =    0,  type = float )
parser.add_argument( '--n_valid'        , default =  1e6,  type = float )
parser.add_argument( '--batch_size'     , default =  1e4,  type = float )
parser.add_argument( '--n_epochs'       , default =  100,  type = int   )
parser.add_argument( '--n_etypes'       , default =    6,  type = int   )
parser.add_argument( '--n_tracks'       , default =    5,  type = int   )
parser.add_argument( '--bkg_ratio'      , default =    5,  type = float )
parser.add_argument( '--n_folds'        , default =    1,  type = int   )
parser.add_argument( '--n_gpus'         , default =    1,  type = int   )
parser.add_argument( '--verbose'        , default =    1,  type = int   )
parser.add_argument( '--patience'       , default =   10,  type = int   )
parser.add_argument( '--sbatch_var'     , default =    0,  type = int   )
parser.add_argument( '--l2'             , default = 1e-6,  type = float )
parser.add_argument( '--dropout'        , default =  0.1,  type = float )
parser.add_argument( '--FCN_neurons'    , default = [200,200], type = int, nargs='+')
parser.add_argument( '--weight_type'    , default = 'none'              )
parser.add_argument( '--train_cuts'     , default = ''                  )
parser.add_argument( '--valid_cuts'     , default = ''                  )
parser.add_argument( '--NN_type'        , default = 'CNN'               )
parser.add_argument( '--scalars'        , default = 'ON'                )
parser.add_argument( '--tracks'         , default = 'ON'                )
parser.add_argument( '--images'         , default = 'ON'                )
parser.add_argument( '--scaling'        , default = 'ON'                )
parser.add_argument( '--t_scaling'      , default = 'OFF'               )
parser.add_argument( '--plotting'       , default = 'OFF'               )
parser.add_argument( '--generator'      , default = 'OFF'               )
parser.add_argument( '--metrics'        , default = 'val_accuracy'      ) #{loss, val_loss, accuracy, val_accuracy}
parser.add_argument( '--host_name'      , default = 'lps'               )
parser.add_argument( '--input_path'     , default = ''                  )
parser.add_argument( '--input_dir'      , default = '0.0-2.5_mc'        )
parser.add_argument( '--output_dir'     , default = 'outputs'           )
parser.add_argument( '--model_in'       , default = ''                  )
parser.add_argument( '--model_out'      , default = 'model.h5'          )
parser.add_argument( '--scaler_in'      , default = ''                  )
parser.add_argument( '--scaler_out'     , default = 'scaler.pkl'        )
parser.add_argument( '--t_scaler_in'    , default = ''                  )
parser.add_argument( '--t_scaler_out'   , default = 't_scaler.pkl'      )
parser.add_argument( '--results_in'     , default = ''                  )
parser.add_argument( '--results_out'    , default = ''                  )
parser.add_argument( '--feature_removal', default = 'OFF'               )
parser.add_argument( '--correlations'   , default = 'OFF'               )
args = parser.parse_args()


# VERIFYING ARGUMENTS
for key in ['n_train', 'n_eval', 'n_valid', 'batch_size']: vars(args)[key] = int(vars(args)[key])
if args.weight_type not in ['bkg_ratio', 'flat', 'match2class', 'match2max', 'none']:
    print('\nWeight type', args.weight_type, 'not recognized --> setting it to none')
    args.weight_type = 'none'
if '.h5' not in args.model_in and args.n_epochs < 1 and args.n_folds==1:
    print('\nERROR: no valid model file\n'); sys.exit()


# CNN PARAMETERS
CNN = {(56,11):{'maps':[100,100], 'kernels':[ (3,5) , (3,5) ], 'pools':[ (2,1) , (2,1) ]},
        (7,11):{'maps':[100,100], 'kernels':[ (3,5) , (3,5) ], 'pools':[ (1,1) , (1,1) ]},
        #(7,11):{'maps':[100,100], 'kernels':[(3,5,3),(3,5,3)], 'pools':[(1,1,1),(1,1,1)]},
      'tracks':{'maps':[200,200], 'kernels':[ (1,1) , (1,1) ], 'pools':[ (1,1) , (1,1) ]}}


# TRAINING VARIABLES
scalars = ['p_Eratio', 'p_Reta'   , 'p_Rhad'      , 'p_Rhad1' , 'p_Rphi'   , 'p_deltaPhiRescaled2'         ,
           'p_ndof'  , 'p_dPOverP', 'p_deltaEta1' , 'p_f1'    , 'p_f3'     , 'p_sct_weight_charge'         ,
           'p_weta2' , 'p_d0'     , 'p_d0Sig'     , 'p_qd0Sig', 'p_nTracks', 'p_numberOfSCTHits'           ,
           'p_eta'   , 'p_TRTPID' , 'p_EptRatio'  , 'p_EoverP', 'p_wtots1' , 'p_numberOfPixelHits'         ,
           'p_charge', 'p_et_calo', 'p_cal_energy', 'p_e'     , 'p_numberOfInnermostPixelHits'             ]
images  = [ 'em_barrel_Lr0',   'em_barrel_Lr1',   'em_barrel_Lr2',   'em_barrel_Lr3', 'em_barrel_Lr1_fine' ,
                                'tile_gap_Lr1',
            'em_endcap_Lr0',   'em_endcap_Lr1',   'em_endcap_Lr2',   'em_endcap_Lr3', 'em_endcap_Lr1_fine' ,
           'lar_endcap_Lr0',  'lar_endcap_Lr1',  'lar_endcap_Lr2',  'lar_endcap_Lr3',
                             'tile_barrel_Lr1', 'tile_barrel_Lr2', 'tile_barrel_Lr3'                       ]
others  = ['mcChannelNumber', 'eventNumber'  , 'p_TruthType', 'p_iffTruth'   , 'p_TruthOrigin', 'p_LHValue',
           'p_LHTight'      , 'p_LHMedium'   , 'p_LHLoose'  , 'p_ECIDSResult', 'p_vertexIndex', 'p_charge' ,
           'p_topoetcone20' , 'p_ptvarcone30', 'p_passWVeto', 'p_passZVeto'  , 'p_ambiguityType'           ,
           'p_firstEgMotherPdgId'            , 'p_firstEgMotherTruthType'    , 'p_firstEgMotherTruthOrigin',
           'averageInteractionsPerCrossing'  , 'p_passPreselection'          , 'p_trigMatches_pTbin'       ,
           'p_numberOfSCTHits', 'p_numberOfPixelHits', 'p_numberOfInnermostPixelHits', 'p_eta', 'p_et_calo']


# SAMPLES CUTS
gen_cuts  = ['(abs(sample["eta"]) <= 2.5)']
#gen_cuts = ['(abs(sample["eta"]) >= 0) & (abs(sample["eta"]) <= 2.47)']
channel_dict = {'Zee' :['361106'], 'ttbar':['410470'], 'Ztautau':['361108'], 'Wtaunu':['361102,361105'],
                'JF17':['423300'], 'JF35' :['423302'], 'JF50'   :['423303'], 'Wenu'  :['361100,361103'],
                'high-pt_PC': ['423107','423108','423109','423110','423111','423112']                  }
#channels = channel_dict['JF17'] + channel_dict['Zee'] + ['0']
#gen_cuts += ['( ' + ''.join([   '(sample["mcChannelNumber"] == '+channels[0]+')']
#                           +[' | (sample["mcChannelNumber"] == '+n+')' for n in channels[1:]]) + ' )']
gen_cuts += ['(sample["mcChannelNumber"] != '+n+')' for n in channel_dict['high-pt_PC']]
if args.train_cuts == '': args.train_cuts = gen_cuts.copy()
else                    : args.train_cuts = gen_cuts + [args.train_cuts]
if args.valid_cuts == '': args.valid_cuts = gen_cuts.copy()
else                    : args.valid_cuts = gen_cuts + [args.valid_cuts]
#args.train_cuts += ['(sample["p_LHValue"] >= -10)']
args.valid_cuts += ['(sample["PixelHits"] >= 2)', '(sample["SCTHits"] + sample["PixelHits"] >= 7)']
args.valid_cuts += ['(sample["p_ambiguityType"] <= 4)']
#args.valid_cuts += ['(sample["p_passWVeto"] == True)', '(sample["p_passZVeto"] == True)']
#args.valid_cuts += ['(sample["p_passPreselection"] == True)', '(sample["p_trigMatches_pTbin"] > 0)']
#args.valid_cuts += ['(sample["p_topoetcone20"]/sample["pt"] < 0.20)']
#args.valid_cuts += ['(sample["p_ptvarcone30" ]/sample["pt"] < 0.15)']


# PERFORMANCE FROM SAVED VALIDATION RESULTS
if os.path.isfile(args.output_dir+'/'+args.results_in) or os.path.islink(args.output_dir+'/'+args.results_in):
    class_eff = validation(args.output_dir, args.results_in, args.plotting,
                           args.n_valid, args.n_etypes, args.valid_cuts)
    plot_history(args.output_dir, hist_file='train_history.pkl')
elif args.results_in != '':
    print('\nERROR: no valid results_in file\n')
if args.results_in != '': sys.exit()


# TRAINING DATA
data_files = get_dataset(args.input_path, args.input_dir, args.host_name)
keys    = set().union(*[h5py.File(data_file,'r').keys() for data_file in data_files])
images  = [key for key in images  if key in keys or key=='tracks']
scalars = [key for key in scalars if key in keys or key=='tracks']
others  = [key for key in others  if key in keys]
if args.scalars != 'ON'                        : scalars = []
if args.tracks  != 'ON' and args.images != 'ON': images  = []
if args.tracks  == 'ON' and args.images != 'ON': images  = ['tracks']
if args.tracks  == 'ON' and args.images == 'ON': images += ['tracks']
if args.feature_removal == 'ON':
    groups = [('em_barrel_Lr1','em_barrel_Lr1_fine'), ('em_barrel_Lr0','em_barrel_Lr2','em_barrel_Lr3')]
    scalars, images, removed_feature = feature_removal(scalars, images, groups=[], index=args.sbatch_var)
    args.output_dir += '/'+removed_feature
if images == []: args.NN_type = 'FCN'
train_data = {'scalars':scalars, 'images':images}
input_data = {**train_data, 'others':others}


# SAMPLES SIZES / AVOIDING MEMORY OVERLOAD
if   args.images == 'ON': n_limit =   20e6
elif args.tracks == 'ON': n_limit =   50e6
else                    : n_limit = 1000e6
if max(args.n_train, args.n_valid) > n_limit: args.generator = 'ON'
sample_size  = sum([len(h5py.File(data_file,'r')['eventNumber']) for data_file in data_files])
args.n_train = [0, min(sample_size, args.n_train)]
args.n_valid = [args.n_train[1], min(args.n_train[1]+args.n_valid, sample_size)]
if args.n_valid[0] == args.n_valid[1]: args.n_valid = args.n_train
args.n_eval = [args.n_valid[0], min(args.n_valid[0]+args.n_eval, sample_size)]
if args.n_eval[0] == args.n_eval[1]: args.n_eval = args.n_valid
#print(args.n_train, args.n_eval, args.n_valid); sys.exit()


# MODEL CREATION / MULTI-GPU DISTRIBUTION
sample = make_sample(data_files[0], [0,1], input_data, args.n_tracks, args.n_etypes)[0]
n_gpus = min(args.n_gpus, len(tf.config.experimental.list_physical_devices('GPU')))
model  = create_model(args.n_etypes, sample, args.NN_type, args.FCN_neurons, CNN,
                      args.l2, args.dropout, train_data, n_gpus)
train_batch_size = args.batch_size                 #* max(1,n_gpus)
valid_batch_size = max(args.batch_size, int(20e3)) #* max(1,n_gpus)


# ARGUMENTS AND VARIABLES SUMMARY
args.scaling   = args.scaling   == 'ON' and list(set(scalars)-{'tracks'}) != []
args.t_scaling = args.t_scaling == 'ON' and 'tracks' in scalars+images
if args.NN_type == 'CNN':
    print('\nCNN ARCHITECTURE:')
    for shape in [shape for shape in CNN if shape in [sample[key].shape[1:] for key in sample]]:
        print(format(str(shape),'>8s')+':', str(CNN[shape]))
print('\nPROGRAM ARGUMENTS:')
args_dict = vars(args).copy()
if len(args.train_cuts) >= 1:
    for n in range(len(args.train_cuts)): args_dict['train_cuts ('+str(n+1)+')'] = args.train_cuts[n]
    args_dict.pop('train_cuts')
if len(args.valid_cuts) >= 1:
    for n in range(len(args.valid_cuts)): args_dict['valid_cuts ('+str(n+1)+')'] = args.valid_cuts[n]
    args_dict.pop('valid_cuts')
print(tabulate(args_dict.items(), tablefmt='psql'))
print('\nTRAINING VARIABLES:')
headers = [           key  for key in train_data if train_data[key]!=[]]
table   = [train_data[key] for key in train_data if train_data[key]!=[]]
length  = max([len(n) for n in table])
table   = list(map(list, zip(*[n+(length-len(n))*[''] for n in table])))
print(tabulate(table, headers=headers, tablefmt='psql')); print()
args.model_in    = args.output_dir+'/'+args.model_in   ; args.model_out    = args.output_dir+'/'+args.model_out
args.scaler_in   = args.output_dir+'/'+args.scaler_in  ; args.scaler_out   = args.output_dir+'/'+args.scaler_out
args.t_scaler_in = args.output_dir+'/'+args.t_scaler_in; args.t_scaler_out = args.output_dir+'/'+args.t_scaler_out
#plot_inputs(args.input_path, args.host_name, input_data, args.n_valid,
#            args.n_tracks, args.n_etypes, args.valid_cuts, args.output_dir)


# LOADIND PRE-TRAINED WEIGHTS
if os.path.isfile(args.model_in):
    print('Loading pre-trained weights from', args.model_in, '\n')
    try:
        model.load_weights(args.model_in)
    except ValueError:
        print('PRE-TRAINED NETWORK ARCHITECTURE')
        model = tf.keras.models.load_model(args.model_in)
        model.summary(); print() #print(model.output_shape)


# GENERATING VALIDATION SAMPLE
scaler, t_scaler = None, None
if args.scaling and os.path.isfile(args.scaler_in):
    print('Loading quantile transform from', args.scaler_in  , '\n')
    scaler = pickle.load(open(args.scaler_in, 'rb'))
if args.t_scaling and os.path.isfile(args.t_scaler_in):
    print('Loading quantile transform from', args.t_scaler_in, '\n')
    t_scaler = pickle.load(open(args.t_scaler_in, 'rb'))
inputs = {'scalars':scalars, 'images':[], 'others':others} if args.generator == 'ON' else input_data
valid_scaler   = None if args.generator=='ON' else scaler
valid_t_scaler = None if args.generator=='ON' else t_scaler
print('VALIDATION SAMPLE: loading', np.diff(args.n_valid)[0], 'electron-candidates')
valid_sample, valid_labels, _ = merge_samples(data_files, args.n_valid, inputs, args.n_tracks,
                                              args.n_etypes, args.valid_cuts, valid_scaler, valid_t_scaler)
#sample_composition(valid_sample); compo_matrix(valid_labels, n_etypes=args.n_etypes)         ; sys.exit()
#sample_analysis(valid_sample, valid_labels, scalars, scaler, args.generator, args.output_dir); sys.exit()


# EVALUATING FEATURES CORRELATIONS
if args.correlations == 'ON':
    from importance import correlations
    correlations(images, scalars, valid_sample, valid_labels, args.input_dir, args.output_dir, args.images)


# TRAINING LOOP
if args.n_epochs > 0:
    for path in list(itertools.accumulate([folder+'/' for folder in args.output_dir.split('/')])):
        try: os.mkdir(path)
        except FileExistsError: pass
    print('Using TensorFlow', tf.__version__                            )
    print('Using'           , n_gpus, 'GPU(s)'                          )
    print('Using'           , args.NN_type, 'architecture with', end=' ')
    print([key for key in train_data if train_data[key] != []], '\n'    )
    print('TRAINING SAMPLE: loading', np.diff(args.n_train)[0], 'electron-candidates')
    if args.t_scaling and not os.path.isfile(args.t_scaler_in) and 'tracks' in images and args.generator == 'ON':
        inputs['images'] = ['tracks']
    train_sample, train_labels, weight_idx = merge_samples(data_files, args.n_train, inputs, args.n_tracks,
                                                           args.n_etypes, args.train_cuts)
    sample_composition(train_sample, 'train'); compo_matrix(valid_labels, train_labels); print() #; sys.exit()
    train_weights, bins = get_sample_weights(train_sample, train_labels, args.weight_type, args.bkg_ratio, hist='pt')
    sample_histograms(valid_sample, valid_labels, train_sample, train_labels, args.n_etypes,
                      train_weights, bins, args.output_dir) ; print() #; sys.exit()
    if args.scaling:
        if not os.path.isfile(args.scaler_in):
            scaler = fit_scaler(train_sample, scalars, args.scaler_out)
            if args.generator != 'ON': valid_sample = apply_scaler(valid_sample, scalars, scaler, verbose='OFF')
        if args.generator != 'ON': train_sample = apply_scaler(train_sample, scalars, scaler, verbose='ON')
    if args.t_scaling:
        if not os.path.isfile(args.t_scaler_in):
            t_scaler = fit_t_scaler(train_sample, args.t_scaler_out)
            if args.generator != 'ON': valid_sample = apply_t_scaler(valid_sample, t_scaler, verbose='OFF')
        if args.generator != 'ON': train_sample = apply_t_scaler(train_sample, t_scaler, verbose='ON')
    callbacks = callback(args.model_out, args.patience, args.metrics)
    print('TRAINING ON SAMPLE', args.n_train)
    if args.generator == 'ON':
        del(train_sample)
        if np.all(train_weights) != None: train_weights = gen_weights(args.n_train, weight_idx, train_weights)
        train_gen = Batch_Generator(data_files, args.n_train, input_data, args.n_tracks, args.n_etypes,
                                    train_batch_size, args.train_cuts, scaler, t_scaler, train_weights, shuffle='ON')
        eval_gen  = Batch_Generator(data_files, args.n_eval , input_data, args.n_tracks, args.n_etypes,
                                    valid_batch_size, args.valid_cuts, scaler, t_scaler, shuffle='OFF')
        training  = model.fit( train_gen, validation_data=eval_gen, max_queue_size=100*max(1,n_gpus),
                               callbacks=callbacks, workers=1, epochs=args.n_epochs, verbose=args.verbose )
    else:
        eval_sample = {key:valid_sample[key][:args.n_eval[1]-args.n_valid[0]] for key in valid_sample}
        eval_labels =      valid_labels     [:args.n_eval[1]-args.n_valid[0]]
        training = model.fit( train_sample, train_labels, validation_data=(eval_sample,eval_labels),
                              callbacks=callbacks, sample_weight=train_weights, batch_size=train_batch_size,
                              epochs=args.n_epochs, verbose=args.verbose )
    model.load_weights(args.model_out); print()
else:
    train_labels = None ; training = None


# PLOTTING PERFORMANCE RESULTS
if args.n_folds > 1:
    valid_probs = cross_valid(valid_sample, valid_labels, scalars, args.output_dir, args.n_folds, data_files,
                              args.n_valid, input_data, args.n_tracks, args.valid_cuts, model, args.generator)
else:
    print('VALIDATING ON SAMPLE', args.n_valid)
    if args.generator == 'ON':
        valid_gen   = Batch_Generator(data_files, args.n_valid, input_data, args.n_tracks, args.n_etypes,
                                      valid_batch_size, args.valid_cuts, scaler, t_scaler, shuffle='OFF')
        valid_probs = model.predict(valid_gen, verbose=args.verbose)
    else:
        valid_probs = model.predict(valid_sample, batch_size=valid_batch_size, verbose=args.verbose)
bkg_rej = valid_results(valid_sample, valid_labels, valid_probs, train_labels,
                        args.n_etypes, args.output_dir, args.plotting)
if '.pkl' in args.results_out:
    args.results_out = args.output_dir+'/'+args.results_out
    if args.feature_removal == 'ON':
        args.results_out = args.output_dir[0:args.output_dir.rfind('/')]+'/'+args.results_out.split('/')[-1]
        try: pickle.dump({removed_feature:bkg_rej}, open(args.results_out,'ab'))
        except IOError: print('FILE ACCESS CONFLICT FOR', removed_feature, '--> SKIPPING FILE ACCESS\n')
        feature_ranking(args.output_dir, args.results_out, scalars, images, groups=[])
    else:
        valid_keys = (set(valid_sample)-set(scalars)-set(images)) | set(others)
        valid_data = ({key:valid_sample[key] for key in valid_keys}, valid_labels, valid_probs)
        pickle.dump(valid_data, open(args.results_out,'wb'), protocol=4)
    print('\nValidation results saved to:', args.results_out, '\n')
if args.plotting == 'ON' and training is not None:
    plot_history(args.output_dir, history=training)
