import yaml
import glob
import pint.models as pm

overwrite = True  # overwrite existing yamls?

# The following is the 12.5-yr git repo
old_timing = "/home/tim/Research/NANOGrav/nanograv_timing_2017/"
old_util = old_timing+"util/"
old_pars = glob.glob(old_timing+"releases/NANOGrav_12yv4/*band/par/*par")

# bad files
badfile = old_util+"bad_ff_files.txt"
# The following will only get the guppi/puppi files
bad_files = [line.split()[0] for line in open(badfile).readlines() if not line.startswith("#")]

# Where the data lives on the notebook server
new_timing = "/nanograv/releases/15y/toagen/releases/2020.11.18-b8d329b"

# Assumes current working dir is timing_analysis/configs/
ta_dir = ".."

# If there are already .yaml files written
current_configs = glob.glob("[BJ]*.yaml")
current_psrs = list(set([f.split(".")[0] for f in current_configs]))

current_timfiles = [line[:-1] for line in open("timfiles.txt").readlines() if not line.startswith("#")]
psrs = list(set([f.split(".")[0] for f in current_timfiles]))

for psr in psrs:
    for toatype in ["nb", "wb"]:
        outname = psr+f".{toatype}.yaml"
        if not overwrite and psr in current_psrs: outname = outname+".auto"
        print(psr, outname)
        uptoatype = toatype.upper()
        fitter = "GLSFitter" if toatype=="nb" else "WidebandTOAFitter"
        snr_cut = 8 if toatype=="nb" else 25
        timlist = [tfile for tfile in current_timfiles if
                   (tfile.startswith(psr) and tfile.endswith(toatype+".tim"))]
        toas_str = yaml.dump({"toas": timlist})
        parfiles = [line for line in old_pars if line.split("/")[-1].split("_")[0]==psr]  # should get both WB and NB parfiles
        if not parfiles:
            if toatype=="nb":
                free_params_str = "[ELONG,ELAT,PMELONG,PMELAT,PX,F0,F1,A1,PB,TASC,EPS1,EPS2,JUMP1]"
            else:
                free_params_str = "[ELONG,ELAT,PMELONG,PMELAT,PX,F0,F1,A1,PB,TASC,EPS1,EPS2,JUMP1,DMJUMP1,DMJUMP2]"
            parfiles = glob.glob(f"{ta_dir}/results/{psr}*.par")
            if parfiles:
                parfile = parfiles[0]
                parfile_str = parfile.split('/')[-1]
            else:
                parfile_str = f"{psr}.basic.par"
        else:
            if toatype=="nb":
                parfile = [pf for pf in parfiles if pf.endswith("12yv4.gls.par")][0] # will not chose t2 model for J1713
            else:
                parfile = [pf for pf in parfiles if pf.endswith("12yv4.wb.gls.par")][0] # will not chose t2 model for J1713
            parfile_str = parfile.split('/')[-1]
            model = pm.get_model(parfile)
            free_params = [p for p in model.free_params if not p.startswith("DMX")]
            if toatype=="wb":
                dmjump_params = [p for p in model.params if p.startswith("DMJUMP")]  # these were fixed in the 12.5-year analysis
                free_params += dmjump_params
            free_params_str = yaml.dump(free_params, default_flow_style=True).replace(" ", "").strip()
        files = ["_".join(ff.split("_")[:3]) for ff in bad_files if ff.find(psr) > 0]
        if files:
            bad_file_str = yaml.dump({"bad-file": files})
            # Fix the indentation
            bad_file_str = bad_file_str.replace("- gu", "    - gu")
            bad_file_str = bad_file_str.replace("- pu", "    - pu")
        else:
            bad_file_str = 'bad-file: ~'
        # currently we are not using the following
        #dropfile = open(old_timing+"working/"+psr+"/"+psr+".epochdrop")
        #bad_toas = [line for line in dropfile.readlines() if not line.startswith("#")]
        #bad_toas_str = yaml.dump(bad_toas)
        template = f'''# This config was autogenerated by write_initial_configs.py
source: {psr}
par-directory: results/
tim-directory: {new_timing}
timing-model: {parfile_str}
compare-model: ~
{toas_str}
# Parameters not included here will be frozen (e.g. DM)
free-params: {free_params_str}
free-dmx: True
toa-type: {uptoatype}
fitter: {fitter}
ephem: DE440
bipm: BIPM2019

# Global/subset TOA excision
ignore:
  mjd-start: ~
  mjd-end: ~
  snr-cut: {snr_cut}
  # Following are designated by ['name','chan','subint']
  bad-toa: ~
  # Designated by [mjd_start,mjd_end] (can have multiple)
  bad-range: ~
  # Following are designated by a basename string to take away all
  # TOAs with that basename (can have multiple)
  {bad_file_str}

# End
'''
        open(outname, "w").write(template)

