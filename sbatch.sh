#!/bin/bash
##SBATCH --account=def-arguinj
##SBATCH --time=12:00:00    # time (DD-HH:MM)
##SBATCH --mem=186G         # memory (per node)
#SBATCH --gres=gpu:4       # Number of GPU(s) per node
#SBATCH --job-name=el-id
#SBATCH --output=outputs/log_files/%x_%A_%a.out
#SBATCH --array=1
export VAR=$SLURM_ARRAY_TASK_ID


# TRAINING ON LPS
singularity shell --nv --bind /lcg,/opt \
/opt/tmp/godin/sing_images/tf-2.1.0-gpu-py3_sing-2.6.sif classifier.sh $VAR


# SAMPLE GENERATION ON LPS
#singularity shell      --bind /lcg,/opt \
#/opt/tmp/godin/sing_images/tf-2.1.0-gpu-py3_sing-2.6.sif presampler.sh


# TRAINING ON BELUGA
#module load singularity/2.6
#singularity shell --nv --bind /project/def-arguinj/dgodin \
#/project/def-arguinj/dgodin/sing_images/tf-2.1.0-gpu-py3_sing-2.6.sif classifier.sh $VAR



