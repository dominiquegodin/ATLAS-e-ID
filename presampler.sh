#python presampler.py --mixing=ON --n_files=10
#python presampler.py --n_e=500e6 --n_tasks=20 --eta_region=1.6-2.5 --sampling=ON --merging=OFF
# python presampler_Olivier.py --n_e=500e6 --n_tasks=20 --sampling=ON --merging=ON --eta_region=0-2.5 --indir=/lcg/storage20/atlas/denis/hdf5/JF17/11151/MC/electron/e-ID
python presampler.py --sampling=ON --merging=OFF --n_tasks=20 --input_dir=0.0-1.3
#python presampler.py --mixing=ON --n_files=20 --input_dir=inputs --output_dir=outputs
#python presampler.py --sampling=OFF --merging=ON
