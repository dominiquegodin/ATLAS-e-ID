# Introduction
This is a TensorFlow framework for the identification of ATLAS electrons by using neural networks.


# Training at LPS  
1) login to atlas16 for GPU's avaibility 
   ```
   ssh -Y atlas16
   ```
2) change to user directory
   ```
   cd /opt/tmp/$USER  
   ```  
3) link data file to user directory
   ```
   ln -s /opt/tmp/godin/el_data/2020-05-28/el_data.h5 .
   ```  
4) clone framework from GitHub
   ```
   git clone https://github.com/dominiquegodin/el_classifier.git  
   ```  
5) enter framework directory
   ```
   cd el_classifier
   ```
6) activate the virtual environment of TensorFlow2.1.0+Python3.6.8 Singularity image
   ```
   singularity shell --nv --bind /opt /opt/tmp/godin/sing_images/tf-2.1.0-gpu-py3_sing-2.6.sif
   ```
   use the flag --nv or not to wether run on GPUs or CPUs
7) start training; see options below
   ```
   python classifier.py [OPTIONS]
   ```
8) for monitoring NVIDIA GPU devices, e.g. memory and power usage, temperature, fan speed, etc.
   ```
   nvidia-smi
   ```


# Training on Beluga Cluster
1) login to Beluga cluster
   ```
   ssh -Y $USER@beluga.calculquebec.ca
   ```
2) change to user directory
   ```
   cd /home/$USER
   ```
3) link data file to user directory
   ```
   ln -s /project/def-arguinj/dgodin/el_data/2020-05-28/el_data.h5 .
   ```
4) clone framework from GitHub
   ```
   git clone https://github.com/dominiquegodin/el_classifier.git
   ```
5) enter framework directory
   ```
   cd el_classifier
   ```

# Using Slurm jobs manager (LPS or Beluga)
1) run classifier.sh script and send jobs to Slurm batch system
   ```
   sbatch sbatch.sh
   ```
2) send array jobs with ID 1 to 10 to Slurm batch system
   ```
   sbatch --array=1-10 sbatch.sh
   ```
2) report status of job
   ```
   squeue
   ```
   or
   ```
   sview
   ```
3) cancel job
   ```
   scancel $job_id
   ```
4) monitor jobs GPU usage at 2s interval
   ```
   srun --jobid $job_id --pty watch -n 2 nvidia-smi
   ```
5) use Slurm interactively and request appropriate ressources on Beluga
   ```
   salloc --time=00:30:00 --cpus-per-task=4 --gres=gpu:1 --mem=128G --x11 --account=def-arguinj
   ```


# classifier.py Options
--n_train     : number of training electrons (default=1e5)

--n_valid     : number of testing electrons (default=1e5)

--batch_size  : size of training batches (default=5000)

--n_epochs    : number of training epochs (default=100)

--n_classes   : number of classes (default=2)

--n_tracks    : number of tracks (default=10)

--n_folds     : number of folds for k-fold cross_validation

--n_gpus      : number of gpus for distributed training (default=4)

--weight_type : name of weighting method, either of 'none' (default),
	       'match2b', 'match2s', 'flattening' should be given 

--train_cuts  : applied cuts on training samples 

--valid_cuts  : applied cuts on validation samples 

--NN_type     : CNN or FCN specify the type of neural networks (default=CNN) 

--scaling     : applies quantile transform to scalar variables when ON (fit performed on train sample
	        and applied to whole sample)  

--cross_valid : performs k-fold cross-validation 

--plotting    : plots accuracy history when ON, distributions separation and ROC curves 

--output_dir  : name of output directory (useful fo running jobs in parallel) 

--model_in    : hdf5 model file from a previous training checkpoint (requires .h5 extension)  

--model_out   : name of hdf5 checkpoint file used for saving and updating the model best weights 

--scaler_in   : name of the pickle file (.pkl) containing scaling transform (quantile) for scalars variables 

--results_in  : name of the pickle file (.pkl) containing validation results 


# Explanations
1) The model and weights are automatically saved to a hdf5 checkpoint for each epoch where the performance
   (either accuracy or loss function) has improved. 
2) An early stopping callback allows the training to stop automatically when the validation performance
   has stop improving for a pre-determined number of epochs (default=10).  
3) Finished or aborted trainings can be resumed from where they were stopped by using previously trained weights
   from other same-model hdf5 checkpoints (see --model_in option).
4) All plots, weights and models are saved by default in the "outputs" directory.
5) To use pre-trained weights and generate plots without re-training, n_epochs = 0 must be specify.
6) In order to optimize data transfer rate, the datafile should be present on the same server of the GPU's.


# Setting up suitable python environment on Compute Canada nodes
See https://docs.computecanada.ca/wiki/Python .

### First time 
Create the environment:
```
module load python/3.6
module load scipy-stack
virtualenv --no-download ~/ENV

### install needed packages...
pip install --no-index --upgrade pip
pip install h5py
pip install --no-index tensorflow_cpu
pip install --no-index tensorflow_gpu
pip install -U scikit-learn
pip install tabulate
pip install scikit-image
```

### Subsequent times
Just load the environment:
```
module load python/3.6
module load scipy-stack
source ~/ENV/bin/activate
```
Voila! To get out of it, `deactivate`.