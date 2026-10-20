#!/bin/bash
#SBATCH --partition=HDCAST
#SBATCH --job-name=extract_mercator        #passed by script
#SBATCH --nodes=1                #passed by script
#SBATCH --ntasks-per-node=1
#SBATCH --exclusive
#SBATCH --mem=230G
#SBATCH --time=5:00:00
#SBATCH --output=log_2012.txt #passed by script

source ~/.bashrc
conda activate loenv

python extract_roms2gdp_postprocessed.py
