import numpy as np, h5py, sys, time
from   sklearn           import metrics
from   scipy.spatial     import distance
from   matplotlib        import pylab
from   matplotlib.ticker import MultipleLocator, FormatStrFormatter, AutoMinorLocator
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as colors


def valid_accuracy(y_true, y_prob):
    y_pred = np.argmax(y_prob, axis=1)
    return np.sum(y_pred==y_true)/len(y_true)


def LLH_rates(sample, y_true):
    LLH_tpr, LLH_fpr = [],[]
    for wp in ['p_LHTight', 'p_LHMedium', 'p_LHLoose']:
        y_class0 = sample[wp][y_true == 0]
        y_class1 = sample[wp][y_true != 0]
        LLH_tpr.append( np.sum(y_class0 == 0)/len(y_class0) )
        LLH_fpr.append( np.sum(y_class1 == 0)/len(y_class1) )
    return LLH_fpr, LLH_tpr


def plot_history(history, output_dir, key='accuracy'):
    if history == None or len(history.epoch) < 2: return
    plt.figure(figsize=(12,8))
    pylab.grid(True)
    val = plt.plot(np.array(history.epoch)+1, 100*np.array(history.history[key]), label='Training')
    plt.plot(np.array(history.epoch)+1, 100*np.array(history.history['val_'+key]), '--',
             color=val[0].get_color(), label='Testing')
    min_acc = np.floor(100*min( history.history[key]+history.history['val_'+key] ))
    max_acc = np.ceil (100*max( history.history[key]+history.history['val_'+key] ))
    plt.xlim([1, max(history.epoch)+1])
    plt.xticks( np.append(1,np.arange(5,max(history.epoch)+2,step=5)) )
    plt.xlabel('Epochs',fontsize=25)
    plt.ylim( max(70,min_acc),max_acc )
    plt.yticks( np.arange(max(80,min_acc),max_acc+1,step=1) )
    plt.ylabel(key.title()+' (%)',fontsize=25)
    plt.legend(loc='lower right', fontsize=20, numpoints=3)
    file_name = output_dir+'/history.png'
    print('Saving training accuracy history to:', file_name, '\n'); plt.savefig(file_name)


def plot_distributions_DG(sample, y_true, y_prob, output_dir, separation=False, bkg='bkg'):
    label_dict = {0:'iso electron', 1:'charge flip'  , 2:'photon conversion'    , 3    :'b/c hadron',
                  4:'light flavor ($\gamma$/e$^\pm$)', 5:'light flavor (hadron)', 'bkg':'background'}
    color_dict = {0:'tab:blue'    , 1:'tab:orange'   , 2:'tab:green'            , 3    :'tab:red'   ,
                  4:'tab:purple'                     , 5:'tab:brown'            , 'bkg':'tab:orange'}
    if y_prob.shape[1] > 2 or separation: label_dict.pop('bkg')
    else: label_dict={0:'iso electron',1:label_dict[bkg]}; color_dict={0:'tab:blue',1:color_dict[bkg]}
    n_classes = len(label_dict)
    def logit(x, delta=1e-16):
        x = np.float64(x); x = np.minimum(x,1-delta); x = np.maximum(x,delta)
        return np.log10(x) - np.log10(1-x)
    def print_JSD(P, Q, idx, color, text):
        plt.text(0.945, 1.01-3*idx/100, 'JSD$_{0,\!'+text+'}$:',
                 {'color':'black', 'fontsize':10}, va='center', ha='right', transform=axes.transAxes)
        plt.text(0.990, 1.01-3*idx/100, format(distance.jensenshannon(P, Q), '.3f'),
                 {'color':color  , 'fontsize':10}, va='center', ha='right', transform=axes.transAxes)
    def class_histo(y_true, y_prob, bins, colors):
        h = np.full((len(bins)-1,n_classes), 0.)
        from utils import make_labels; class_labels = make_labels(sample, n_classes)
        for n in np.arange(n_classes):
            class_probs   = y_prob[:,0][class_labels==n]
            class_weights = len(class_probs)*[100/len(y_true)] #len(class_probs)*[100/len(class_probs)]
            h[:,n] = pylab.hist(class_probs, bins=bins, label='class '+str(n)+': '+label_dict[n],
                                histtype='step', weights=class_weights, log=True, color=colors[n], lw=2)[0]
        if n_classes == 2: colors = len(colors)*['black']
        if True:
            for n in np.arange(1, n_classes):
                new_y_true = y_true[np.logical_or(y_true==0, class_labels==n)]
                new_y_prob = y_prob[np.logical_or(y_true==0, class_labels==n)]
                fpr, tpr, threshold = metrics.roc_curve(new_y_true, new_y_prob[:,0], pos_label=0)
                axes.axvline(threshold[np.argmax(tpr-fpr)], ymin=0, ymax=1, ls='--', lw=1, color=colors[n])
        for n in np.arange(1, n_classes): print_JSD(h[:,0], h[:,n], n, colors[n], str(n))
        if n_classes > 2: print_JSD(h[:,0], np.sum(h[:,1:],axis=1), n_classes, 'black', '\mathrm{bkg}')
    plt.figure(figsize=(12,16))
    plt.subplot(2, 1, 1); pylab.grid(True); axes = plt.gca()
    pylab.xlim(0,100); pylab.ylim(1e-5 if n_classes>2 else 1e-5, 1e2)
    plt.xticks(np.arange(0,101,step=10))
    #pylab.xlim(0,10); pylab.ylim(1e-2 if n_classes>2 else 1e-2, 1e2)
    #plt.xticks(np.arange(0,11,step=1))
    bin_step = 0.5; bins = np.arange(0, 100+bin_step, bin_step)
    class_histo(y_true, 100*y_prob, bins, color_dict)
    plt.xlabel('Signal Probability (%)', fontsize=25)
    plt.ylabel('Distribution (% per '+ str(bin_step) +' % bin)', fontsize=25)
    plt.legend(loc='upper center', fontsize=16 if n_classes==2 else 14, numpoints=3)
    plt.subplot(2, 1, 2); pylab.grid(True); axes = plt.gca()
    x_min=-10; x_max=6; pylab.xlim(x_min, x_max); pylab.ylim(1e-4 if n_classes>2 else 1e-4, 1e1)
    pos  =                   [  10**float(n)      for n in np.arange(x_min,0)       ]
    pos += [0.5]           + [1-10**float(n)      for n in np.arange(-1,-x_max-1,-1)]
    lab  =                   ['$10^{'+str(n)+'}$' for n in np.arange(x_min+2,0)     ]
    lab += [1,10,50,90,99] + ['99.'+n*'9'         for n in np.arange(1,x_max-1)     ]
    #x_min=-10; x_max=-1; pylab.xlim(x_min, x_max); pylab.ylim(1e-2 if n_classes>2 else 1e-4, 1e2)
    #pos  =                   [  10**float(n)      for n in np.arange(x_min,0)       ]
    #lab  =                   ['$10^{'+str(n)+'}$' for n in np.arange(x_min+2,0)     ] + [1,10]
    #lab += ['0.50   '] + ['$1\!-\!10^{'+str(n)+'}$' for n in np.arange(-1,-x_max-1,-1)]
    plt.xticks(logit(np.array(pos)), lab, rotation=15)
    bin_step = 0.1; bins = np.arange(x_min-1, x_max+1, bin_step)
    y_prob[:,0] = logit(y_prob[:,0])
    class_histo(y_true, y_prob, bins, color_dict)
    plt.xlabel('Signal Probability (%)', fontsize=25)
    plt.ylabel('Distribution (% per bin '+str(bin_step)+')', fontsize=25)
    location = 'upper left' if n_classes==2 else 'upper left'
    plt.legend(loc=location, fontsize=16 if n_classes==2 else 14, numpoints=3)
    plt.subplots_adjust(top=0.95, bottom=0.1, hspace=0.2)
    file_name = output_dir+'/distributions.png'
    print('Saving test sample distributions to:', file_name); plt.savefig(file_name)


def plot_ROC_curves(sample, y_true, y_prob, ROC_type, output_dir):
    LLH_fpr, LLH_tpr = LLH_rates(sample, y_true)
    fpr, tpr, threshold = metrics.roc_curve(y_true, y_prob[:,0], pos_label=0)
    signal_ratio        = np.sum(y_true==0)/len(y_true)
    accuracy            = tpr*signal_ratio + (1-fpr)*(1-signal_ratio)
    best_tpr, best_fpr  = tpr[np.argmax(accuracy)], fpr[np.argmax(accuracy)]
    colors = [ 'red', 'blue', 'green' ]
    labels = [ 'LLH tight', 'LLH medium', 'LLH loose' ]
    sig_eff, bkg_eff = '$\epsilon_{\operatorname{sig}}$', '$\epsilon_{\operatorname{bkg}}$'
    plt.figure(figsize=(12,8)); pylab.grid(True); axes = plt.gca()
    if ROC_type == 1:
        plt.xlim([0.6, 1]); plt.ylim([0.9, 1-1e-4])
        plt.xticks([0.6, 0.7, 0.8, 0.9, 1], [60, 70, 80, 90, 100])
        plt.yscale('logit')
        plt.yticks([0.9, 0.99, 0.999, 0.9999], [90, 99, 99.9, 99.99])
        axes.xaxis.set_minor_locator(AutoMinorLocator(10))
        axes.xaxis.set_minor_formatter(plt.NullFormatter())
        axes.yaxis.set_minor_formatter(plt.NullFormatter())
        plt.xlabel('Signal Efficiency '+sig_eff+' (%)', fontsize=25)
        plt.ylabel('Background Rejection $1\!-\!$'+bkg_eff+' (%)', fontsize=25)
        plt.text(0.8, 0.67, 'AUC: '+format(metrics.auc(fpr,tpr),'.4f'),
                 {'color':'black', 'fontsize':22},  va='center', ha='center', transform=axes.transAxes)
        val = plt.plot(tpr, (1-fpr), label='Signal vs Background', color='#1f77b4', lw=2)
        plt.scatter( best_tpr, (1-best_fpr), s=40, marker='o', c=val[0].get_color(),
                     label="{0:<16s} {1:>3.2f}%".format('Best Accuracy:', 100*max(accuracy)) )
        for LLH in zip(LLH_tpr, LLH_fpr, colors, labels):
            plt.scatter(LLH[0], 1-LLH[1], s=40, marker='o', c=LLH[2], label='('+format(100*LLH[0],'.1f')
                        +'%, '+format(100*(1-LLH[1]),'.1f')+')'+r'$\rightarrow$'+LLH[3])
        plt.legend(loc='upper right', fontsize=15, numpoints=3)
    if ROC_type == 2:
        pylab.grid(False)
        len_0 = np.sum(fpr==0)
        x_min = min(60, 10*np.floor(10*LLH_tpr[0]))
        if fpr[np.argwhere(tpr >= x_min/100)[0]] != 0:
            y_max = 100*np.ceil(max(1/fpr[np.argwhere(tpr >= x_min/100)[0]], 1/LLH_fpr[0])/100)
        else: y_max = 10000
        plt.xlim([x_min, 100]); plt.ylim([1, y_max])
        axes.xaxis.set_major_locator(MultipleLocator(10))
        axes.xaxis.set_minor_locator(AutoMinorLocator(10))
        axes.yaxis.set_minor_locator(AutoMinorLocator(5))
        LLH_scores = [1/fpr[np.argwhere(tpr >= value)[0]] for value in LLH_tpr]
        for n in np.arange(len(LLH_scores)):
            axes.axhline(LLH_scores[n], xmin=(LLH_tpr[n]-x_min/100)/(1-x_min/100), xmax=1,
            ls='--', linewidth=0.5, color='#1f77b4')
            axes.axvline(100*LLH_tpr[n], ymin=abs(1/LLH_fpr[n]-1)/(plt.yticks()[0][-1]-1),
            ymax=abs(LLH_scores[n]-1)/(plt.yticks()[0][-1]-1), ls='--', linewidth=0.5, color='tab:blue')
        for val in LLH_scores:
            plt.text(100.2, val, str(int(val)), {'color': '#1f77b4', 'fontsize': 10}, va="center", ha="left")
        axes.yaxis.set_ticks( np.append([1],plt.yticks()[0][1:]) )
        plt.xlabel('Signal Efficiency '+sig_eff+' (%)', fontsize=25)
        plt.ylabel('Background Rejection 1/'+bkg_eff, fontsize=25)
        val = plt.plot(100*tpr[len_0:], 1/fpr[len_0:], label='Signal vs Background', color='#1f77b4', lw=2)
        if best_fpr != 0:
            plt.scatter( 100*best_tpr, 1/best_fpr, s=40, marker='o', c=val[0].get_color(),
                         label="{0:<15s} {1:>3.2f}%".format('Best Accuracy:',100*max(accuracy)), zorder=10 )
        for LLH in zip( LLH_tpr, LLH_fpr, colors, labels ):
            plt.scatter( 100*LLH[0], 1/LLH[1], s=40, marker='o', c=LLH[2], label='('+format(100*LLH[0],'.1f')
                         +'%, '+str(format(1/LLH[1],'>3.0f'))+')'+r'$\rightarrow$'+LLH[3] )
        plt.legend(loc='upper right', fontsize=15, numpoints=3)
    if ROC_type == 3:
        def make_plot(location):
            plt.xlabel('Signal Probability as Threshold (%)', fontsize=25); plt.ylabel('(%)',fontsize=25)
            val_1 = plt.plot(threshold[1:],   tpr[1:], color='tab:blue'  , label='Signal Efficiency'   , lw=2)
            val_2 = plt.plot(threshold[1:], 1-fpr[1:], color='tab:orange', label='Background Rejection', lw=2)
            val_3 = plt.plot(threshold[1:], accuracy[1:], color='black'  , label='Accuracy', zorder=10 , lw=2)
            for LLH in zip(LLH_tpr, LLH_fpr):
                p1 = plt.scatter(threshold[np.argwhere(tpr>=LLH[0])[0]], LLH[0],
                                 s=40, marker='o', c=val_1[0].get_color())
                p2 = plt.scatter(threshold[np.argwhere(tpr>=LLH[0])[0]], 1-LLH[1],
                                 s=40, marker='o', c=val_2[0].get_color())
            l1 = plt.legend([p1, p2], ['LLH '+sig_eff, 'LLH $1\!-\!$'+bkg_eff], loc='lower left', fontsize=13)
            #std_accuracy = valid_accuracy(y_true, y_prob)
            #plt.scatter( 0.5, std_accuracy, s=30, marker='D', c=val_3[0].get_color(),
            #             label="{0:<10s} {1:>5.2f}%".format('Standard Accuracy:', std_accuracy), zorder=10 )
            plt.scatter( best_threshold, max(accuracy), s=40, marker='o', c=val_3[0].get_color(),
                         label='{0:<10s} {1:>5.2f}%'.format('Best Accuracy:',100*max(accuracy)), zorder=10 )
            plt.legend(loc=location, fontsize=15, numpoints=3); plt.gca().add_artist(l1)
        best_threshold = threshold[np.argmax(accuracy)]
        plt.figure(figsize=(12,16))
        plt.subplot(2, 1, 1); pylab.grid(True); axes = plt.gca()
        plt.xlim([0, 1]);   plt.xticks(np.arange(0,1.01,0.1)   , np.arange(0,101,10))
        plt.ylim([0.6, 1]); plt.yticks(np.arange(0.6,1.01,0.05), np.arange(60,101,5))
        make_plot('lower center')
        plt.subplot(2, 1, 2); pylab.grid(True); axes = plt.gca()
        x_min=-2; x_max=3; y_min=0.1; y_max=1-1e-4;
        pylab.ylim(y_min, y_max); pylab.xlim(10**x_min, 1-10**(-x_max))
        pos  =                       [  10**float(n)  for n in np.arange(x_min,0)           ]
        pos += [0.5]               + [1-10**float(n)  for n in np.arange(-1,-x_max-1,-1)    ]
        lab  =                       [ '0.'+n*'0'+'1' for n in np.arange(abs(x_min)-3,-1,-1)]
        lab += [1, 10, 50, 90, 99] + ['99.'+n*'9'     for n in np.arange(1,x_max-1)         ]
        plt.xscale('logit'); plt.xticks(pos, lab)
        plt.yscale('logit'); plt.yticks([0.1, 0.5, 0.9, 0.99, 0.999, 0.9999], [10, 50, 90, 99, 99.9, 99.99])
        axes.xaxis.set_minor_formatter(plt.NullFormatter())
        axes.yaxis.set_minor_formatter(plt.NullFormatter())
        make_plot('upper center')
    if ROC_type == 4:
        best_tpr = tpr[np.argmax(accuracy)]
        plt.xlim([60, 100.0])
        plt.ylim([80, 100.0])
        plt.xticks(np.arange(60,101,step=5))
        plt.yticks(np.arange(80,101,step=5))
        plt.xlabel('Signal Efficiency (%)',fontsize=25)
        plt.ylabel('(%)',fontsize=25)
        plt.plot(100*tpr[1:], 100*(1-fpr[1:]), label='Background rejection', color='darkorange', lw=2)
        val = plt.plot(100*tpr[1:], 100*accuracy[1:], label='Accuracy', color='black', lw=2, zorder=10)
        plt.scatter( 100*best_tpr, 100*max(accuracy), s=40, marker='o', c=val[0].get_color(),
                     label="{0:<10s} {1:>5.2f}%".format('Best Accuracy:',100*max(accuracy)), zorder=10 )
        plt.legend(loc='lower center', fontsize=15, numpoints=3)
    file_name = output_dir+'/ROC'+str(ROC_type)+'_curve.png'
    print('Saving test sample ROC'+str(ROC_type)+' curve to:   ', file_name); plt.savefig(file_name)


def combine_ROC_curves(output_dir, CNN_dict):
    import multiprocessing as mp, pickle
    from scipy.interpolate import make_interp_spline
    from utils import NN_weights
    def mp_roc(idx, output_dir, return_dict):
        #result_file = output_dir+'/'+'class_0_vs_'+str(bkg_class)+'/'+'results_0_vs_'+str(bkg_class)+'.out'
        #result_file = output_dir+'/'+str(idx)+'-tracks'+'/'+'results.pkl'
        result_file = output_dir+'/'+str(idx)+'_to_1'+'/'+'results.pkl'
        sample, labels, probs = pickle.load(open(result_file, 'rb'))
        fpr, tpr, threshold = metrics.roc_curve(labels, probs[:,0], pos_label=0)
        LLH_fpr, LLH_tpr = LLH_rates(sample, labels)
        print('LOADING VALIDATION RESULTS FROM', result_file)
        return_dict[idx] = fpr, tpr, threshold, LLH_fpr, LLH_tpr
    manager   = mp.Manager()   ; return_dict = manager.dict()
    idx_list  = [1,1.7,2,3,4,5,6,7,8,9,10]
    var_name    = '$r_{sig}:r_{bkg}$'
    processes = [mp.Process(target=mp_roc, args=(idx, output_dir, return_dict)) for idx in idx_list]
    for job in processes: job.start()
    for job in processes: job.join()
    plt.figure(figsize=(12,8)); pylab.grid(True); axes = plt.gca()
    file_name = output_dir+'/'+'ROC1_curve.png'
    for LLH_tpr in [0.7, 0.8, 0.9]:
        bkg_rej  = [1/return_dict[idx][0][np.argwhere(return_dict[idx][1] >= LLH_tpr)[0]][0]
                    for idx in idx_list]
        bkg_rej /= np.mean(bkg_rej)
        #n_weights = [NN_weights((5,13), CNN_dict, [200, 200], 2) for idx in idx_list]
        #bkg_rej   = [1e5*bkg_rej[n]/n_weights[n] for n in np.arange(len(idx_list))]
        plt.scatter(idx_list, bkg_rej, s=40, marker='o')
        idx_array    = np.linspace(min(idx_list), max(idx_list), 1000)
        spline       = make_interp_spline(idx_list, bkg_rej, k=3)
        plt.plot(idx_array, spline(idx_array), label=format(100*LLH_tpr,'.0f')+'% sig. eff.')
    plt.xlim([min(idx_list)-1, max(idx_list)+1])
    axes.xaxis.set_major_locator(MultipleLocator(1))
    #plt.ylim([0, 1500])
    #axes.yaxis.set_major_locator(MultipleLocator(100))
    plt.ylim([0.9, 1.1])
    axes.yaxis.set_major_locator(MultipleLocator(0.05))
    #plt.xlabel('Maximum Number of Tracks',fontsize=25)
    plt.xlabel('Ratio bkg/sig (for training)',fontsize=25)
    plt.ylabel('1/(Background Efficiency)',fontsize=25)
    #plt.ylabel('1/(Bkg. Eff.) over Mean',fontsize=25)
    plt.legend(loc='lower center', fontsize=15, numpoints=3)
    plt.savefig(file_name)
    plt.figure(figsize=(12,8)); pylab.grid(True); axes = plt.gca()
    file_name = output_dir+'/'+'ROC2_curve.png'
    x_min = []; y_max = []
    for idx in idx_list:
        fpr, tpr, threshold, LLH_fpr, LLH_tpr = return_dict[idx]; len_0  = np.sum(fpr==0)
        x_min += [min(60, 10*np.floor(10*LLH_tpr[0]))]
        y_max += [100*np.ceil(max(1/fpr[np.argwhere(tpr >= x_min[-1]/100)[0]], 1/LLH_fpr[0])/100)]
        val = plt.plot(100*tpr[len_0:], 1/fpr[len_0:], label=var_name+' = 1:'+str(idx), lw=2)
        #label = str(bkg_class) if bkg_class != 0 else 'others'
        #val = plt.plot(100*tpr[len_0:], 1/fpr[len_0:], label='class 0 vs '+label, lw=2)
        #for LLH in zip(LLH_tpr, LLH_fpr):
        #    plt.scatter(100*LLH[0], 1/LLH[1], s=40, marker='o', c=val[0].get_color())
    plt.xlim([min(x_min), 100])
    plt.ylim([1, 3000])  #plt.ylim([1, max(y_max)])
    axes.xaxis.set_major_locator(MultipleLocator(10))
    axes.yaxis.set_major_locator(MultipleLocator(500))
    axes.yaxis.set_ticks( np.append([1], np.arange(500,3500,500)) )
    plt.xlabel('Signal Efficiency (%)',fontsize=25)
    plt.ylabel('1/(Background Efficiency)',fontsize=25); #plt.yscale("log")
    plt.legend(loc='upper right', fontsize=15, numpoints=3)
    plt.savefig(file_name); sys.exit()


def cal_images(sample, labels, layers, output_dir, mode='random', scale='free', soft=True):
    import multiprocessing as mp
    def get_image(sample, labels, e_class, key, mode, image_dict):
        start_time = time.time()
        if mode == 'random':
            while True:
                image = abs(sample[key][np.random.choice(np.where(labels==e_class)[0])])
                if np.max(image) !=0: break
        if mode == 'mean': image = np.mean(sample[key][labels==e_class], axis=0)
        if mode == 'std' : image = np.std (sample[key][labels==e_class], axis=0)
        print('plotting layer '+format(key,length+'s')+' for class '+str(e_class), end='', flush=True)
        print(' (', '\b'+format(time.time() - start_time, '2.1f'), '\b'+' s)')
        image_dict[(e_class,key)] = image
    layers    = [layer for layer in layers if layer in sample.keys()]
    n_classes = max(labels)+1; length = str(max(len(n) for n in layers))
    manager   =  mp.Manager(); image_dict = manager.dict()
    processes = [mp.Process(target=get_image, args=(sample, labels, e_class, key, mode, image_dict))
                 for e_class in np.arange(n_classes) for key in layers]
    print('PLOTTING CALORIMETER IMAGES (mode='+mode+', scale='+str(scale)+')')
    for job in processes: job.start()
    for job in processes: job.join()
    file_name = output_dir+'/cal_images.png'
    print('SAVING IMAGES TO:', file_name, '\n')
    fig = plt.figure(figsize=(7,14)) if n_classes == 2 else plt.figure(figsize=(18,14))
    for e_class in np.arange(n_classes):
        if scale == 'class': vmax = max([np.max(image_dict[(e_class,key)]) for key in layers])
        for key in layers:
            image_dict[(e_class,key)] -= min(0,np.min(image_dict[(e_class,key)]))
            #image_dict[(e_class,key)] = abs(image_dict[(e_class,key)])
            if scale == 'layer':
                vmax = max([np.max(image_dict[(e_class,key)]) for e_class in np.arange(n_classes)])
            if scale == 'free' : vmax = np.max(image_dict[(e_class,key)])
            plot_image(100*image_dict[(e_class,key)], n_classes, e_class, layers, key, 100*vmax, soft)
    wspace = -0.1 if n_classes == 2 else 0.2
    fig.subplots_adjust(left=0.05, top=0.95, bottom=0.05, right=0.95, hspace=0.6, wspace=wspace)
    fig.savefig(file_name); sys.exit()


def plot_image(image, n_classes, e_class, layers, key, vmax, soft=True):
    class_dict = {0:'iso electron',  1:'charge flip' , 2:'photon conversion', 3:'b/c hadron',
                  4:'light flavor ($\gamma$/e$^\pm$)', 5:'light flavor (hadron)'}
    layer_dict = {'em_barrel_Lr0'     :'presampler'            , 'em_barrel_Lr1'  :'EM cal $1^{st}$ layer' ,
                  'em_barrel_Lr1_fine':'EM cal $1^{st}$ layer' , 'em_barrel_Lr2'  :'EM cal $2^{nd}$ layer' ,
                  'em_barrel_Lr3'     :'EM cal $3^{rd}$ layer' , 'tile_barrel_Lr1':'had cal $1^{st}$ layer',
                  'tile_barrel_Lr2'   :'had cal $2^{nd}$ layer', 'tile_barrel_Lr3':'had cal $3^{rd}$ layer'}
    if n_classes ==2: class_dict[1] = 'background'
    e_layer  = layers.index(key)
    n_layers = len(layers)
    plot_idx = n_classes*e_layer + e_class+1
    plt.subplot(n_layers, n_classes, plot_idx)
    title   = class_dict[e_class]+'\n('+layer_dict[key]+')' #layer_dict[key]+'\n('+class_dict[e_class]+')'
    limits  = [-0.13499031, 0.1349903, -0.088, 0.088]
    x_label = '$\phi$'                             if e_layer == n_layers-1 else ''
    x_ticks = [limits[0],-0.05,0.05,limits[1]]     if e_layer == n_layers-1 else []
    y_label = '$\eta$'                             if e_class == 0          else ''
    y_ticks = [limits[2],-0.05,0.0,0.05,limits[3]] if e_class == 0          else []
    plt.title(title,fontweight='normal', fontsize=12)
    plt.xlabel(x_label,fontsize=15); plt.xticks(x_ticks)
    plt.ylabel(y_label,fontsize=15); plt.yticks(y_ticks)
    plt.imshow(np.float32(image), cmap='Reds', interpolation='bilinear' if soft else None,
               extent=limits, vmax=1 if np.max(image)==0 else vmax) #norm=colors.LogNorm(1e-3,vmax))
    plt.colorbar(pad=0.02)


def plot_scalars(sample, sample_trans, variable):
    bins = np.arange(-1,1,0.01)
    fig = plt.figure(figsize=(18,8))
    plt.subplot(1,2,1)
    pylab.xlim(-1,1)
    plt.title('Histogram')
    plt.xlabel('Value')
    plt.ylabel('Number of Entries')
    #pylab.hist(sample_trans[variable], bins=bins, histtype='step', density=True)
    pylab.hist(sample      [variable], bins=bins, histtype='step', density=False)
    plt.subplot(1,2,2)
    plt.title('Histogram')
    plt.xlabel('Value')
    plt.ylabel('Number of Entries')
    pylab.hist(sample_trans[variable], bins=bins)
    file_name = 'outputs/plots/scalars/'+variable+'.png'
    print('Printing:', file_name)
    plt.savefig(file_name)


def plot_tracks(tracks, labels, variable):
    tracks_var = {'efrac':{'idx':0, 'mean_lim':( 0,      3), 'max_lim':(0,    2), 'diff_lim':(0,    1)},
                  'deta' :{'idx':1, 'mean_lim':( 0, 0.0005), 'max_lim':(0, 0.03), 'diff_lim':(0, 0.04)},
                  'dphi' :{'idx':2, 'mean_lim':( 0,  0.001), 'max_lim':(0,  0.1), 'diff_lim':(0, 0.05)},
                  'd0'   :{'idx':3, 'mean_lim':( 0,    0.2), 'max_lim':(0,  0.1), 'diff_lim':(0,  0.3)},
                  'z0'   :{'idx':4, 'mean_lim':( 0,    0.5), 'max_lim':(0,  0.3), 'diff_lim':(0,   10)}}
    classes    = np.arange(max(labels)+1)
    n_e        = np.arange(len(labels)  )
    n_tracks   = np.sum(abs(tracks), axis=2)
    n_tracks   = np.array([len(np.where(n_tracks[n,:]!=0)[0]) for n in n_e])
    var        = tracks[..., tracks_var[variable]['idx']]
    var_mean   = np.array([np.mean(    var[n,:n_tracks[n]])  if n_tracks[n]!=0 else None for n in n_e])
    var_max    = np.array([np.max (abs(var[n,:n_tracks[n]])) if n_tracks[n]!=0 else None for n in n_e])
    var_diff   = np.array([np.mean(np.diff(np.sort(var[n,:n_tracks[n]])))
                           if n_tracks[n]>=2 else None for n in n_e])
    var_diff   = np.array([(np.max(var[n,:n_tracks[n]]) - np.min(var[n,:n_tracks[n]]))/(n_tracks[n]-1)
                           if n_tracks[n]>=2 else None for n in n_e])
    var_mean   = [var_mean[np.logical_and(labels==n, var_mean!=None)] for n in classes]
    var_max    = [var_max [np.logical_and(labels==n, var_max !=None)] for n in classes]
    var_diff   = [var_diff[np.logical_and(labels==n, var_diff!=None)] for n in classes]
    n_tracks   = [n_tracks[labels==n                                ] for n in classes]
    trk_mean   = [np.mean(n_tracks[n])                                for n in classes]
    fig  = plt.figure(figsize=(18,7))
    xlim = (0, 15)
    bins = np.arange(xlim[0], xlim[1]+2, 1)
    for n in [1,2]:
        plt.subplot(1,2,n); axes = plt.gca()
        plt.xlim(xlim)
        plt.xlabel('Number of tracks'      , fontsize=20)
        plt.xticks( np.arange(xlim[0],xlim[1]+1,1) )
        plt.ylabel('Normalized entries (%)', fontsize=20)
        title = 'Track number distribution (' + str(len(classes)) + '-class)'
        if n == 1: title += '\n(individually normalized)'
        weights = [len(n_tracks[n]) for n in classes] if n==1 else len(classes)*[len(labels)]
        weights = [len(n_tracks[n])*[100/weights[n]] for n in classes]
        plt.title(title, fontsize=20)
        label  =  ['class '+str(n)+' (mean: '+format(trk_mean[n],'3.1f')+')' for n in classes]
        plt.hist([n_tracks[n] for n in classes][::-1], bins=bins, lw=2, align='left',
                 weights=weights[::-1], label=label[::-1], histtype='step')
        plt.text(0.99, 0.05, '(sample: '+str(len(n_e))+' e)', {'color': 'black', 'fontsize': 12},
                 ha='right', va= 'center', transform=axes.transAxes)
        plt.legend(loc='upper right', fontsize=13)
    file_name = 'outputs/plots/tracks_number.png'; print('Printing:', file_name)
    plt.savefig(file_name)
    fig     = plt.figure(figsize=(22,6)); n = 1
    metrics = {'mean':(var_mean, 'Average'), 'max':(var_max, 'Maximum absolute'),
               'diff':(var_diff, 'Average difference')}
    #metrics = {'mean':(var_mean, 'Average'), 'max':(var_mean, 'Average'),
    #           'diff':(var_mean, 'Average')}
    for metric in metrics:
        plt.subplot(1, 3, n); axes = plt.gca(); n+=1
        n_e    = sum([len(metrics[metric][0][n]) for n in classes])
        x1, x2 = tracks_var[variable][metric+'_lim']
        bins   = np.arange(0.9*x1, 1.1*x2, (x2-x1)/100)
        plt.xlim([x1, x2])
        plt.title (metrics[metric][1] + ' value of ' + str(variable) + '\'s', fontsize=20)
        plt.xlabel(metrics[metric][1] + ' value'                            , fontsize=20)
        plt.ylabel('Normalized entries (%)'                                 , fontsize=20)
        #weights = [len(metrics[metric][0][n])*[100/len(metrics[metric][0][n])] for n in classes]
        weights = [len(metrics[metric][0][n])*[100/n_e] for n in classes]
        plt.hist([metrics[metric][0][n] for n in classes][::-1], weights=weights[::-1], stacked=False,
                 histtype='step', label=['class '+str(n) for n in classes][::-1], bins=bins, lw=2)
        plt.text(0.01, 0.97, '(sample: '+str(n_e)+' e)', {'color': 'black', 'fontsize': 12},
                 ha='left', va= 'center', transform=axes.transAxes)
        plt.legend(loc='upper right', fontsize=13)
    file_name = 'outputs/plots/tracks_'+str(variable)+'.png'; print('Printing:', file_name)
    plt.savefig(file_name)
