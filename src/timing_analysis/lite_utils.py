import sys
import numpy as np
import astropy.units as u
from astropy import log
from astropy.io import fits
import logging
import matplotlib.pyplot as plt
import time
import warnings
from datetime import datetime
from datetime import date
import yaml
import os
import timing_analysis.par_checker as pc
from ipywidgets import widgets
import pypulse

# Read tim/par files
import pint.toa as toa
import pint.models as models
import pint.residuals
from pint.modelutils import model_equatorial_to_ecliptic

from pint.models.parameter import maskParameter
from pint.models.timing_model import Component

def write_par(fitter,toatype='',addext='',outfile=None):
    """Writes a timing model object to a par file in the working directory.

    Parameters
    ==========
    fitter: `pint.fitter` object
    toatype: str, optional
        if set, adds nb/wb.par
    addext: str, optional
        if set, adds extension to date
    outfile: str, optional
        if set, overrides default naming convention
    """
    if outfile is None:
        source = fitter.get_allparams()['PSR'].value
        date_str = date.today().strftime('%Y%m%d')
        if toatype:
            outfile = f'{source}_PINT_{date_str}{addext}.{toatype.lower()}.par'
        else:
            outfile = f'{source}_PINT_{date_str}{addext}.par'

    with open(outfile, 'w') as fout:
        fout.write(fitter.model.as_parfile())

def write_tim(fitter,toatype='',addext='',outfile=None,commentflag=None):
    """Writes TOAs to a tim file in the working directory.

    Parameters
    ==========
    fitter: `pint.fitter` object
    toatype: str, optional
        if set, adds nb/wb.par
    addext: str, optional
        if set, adds extension to date
    outfile: str, optional
        if set, overrides default naming convention
    commentflag: str or None, optional
        if a string, and that string is a TOA flag,
        that TOA will be commented in the output file;
        if None (or non-string), no TOAs will be commented.
    """
    if outfile is None:
        source = fitter.get_allparams()['PSR'].value
        date_str = date.today().strftime('%Y%m%d')
        if toatype:
            outfile = f'{source}_PINT_{date_str}{addext}.{toatype.lower()}.tim'
        else:
            outfile = f'{source}_PINT_{date_str}{addext}.tim'

    
    fitter.toas.write_TOA_file(outfile, format='tempo2',commentflag=commentflag)

def find_excise_file(outfile_basename,intermediate_results='/nanograv/share/15yr/timing/intermediate/'):
    """Writes TOAs to a tim file in the working directory.

    Parameters
    ==========
    outfile_basename: str
        e.g. J1234+5678.nb, use tc.get_outfile_basename()
    intermediate_results: str, optional
        base directory where intermediate results are stored
    """
    outlier_dir = os.path.join(intermediate_results,'outlier',outfile_basename)
    excise_file_only = f'{outfile_basename}_excise.tim'
    excise_file = os.path.join(outlier_dir,excise_file_only)
    noc_file = excise_file_only.replace('.tim','-noC.tim')

    # Check for existence of excise file, return filename (else, None)
    if os.path.exists(excise_file):
        # Check for 'C ' instances
        with open(excise_file,'r') as fi:
            timlines = fi.readlines()
            Ncut = 0
            for i in range(len(timlines)):
                if timlines[i].startswith('C '):
                    timlines[i] = timlines[i].lstrip('C ')
                    Ncut += 1

        # If any, remove them and write noc_file to read, else read the existing file
        if Ncut:
            log.info(f"Removing {Ncut} instances of 'C ', writing {noc_file}.")
            with open(noc_file,'w') as fo:
                fo.writelines(timlines)
            excise_file = noc_file
        else:
            pass

        return excise_file

    else:
        log.warning(f'Excise file does not exist: {excise_file}')
        return None 

def write_include_tim(source,tim_file_list):
    """Writes file listing tim files to load as one PINT toa object (using INCLUDE).
       DEPRECATED...?

    Parameters
    ==========
    source: string
        pulsar name
    tim_file_list: list
        tim files to include

    Returns
    =======
    out_tim: tim filename string
    """
    out_tim = '%s.tim' % (source)
    f = open(out_tim,'w')

    for tf in tim_file_list:
        f.write('INCLUDE %s\n' % (tf))

    f.close()
    return out_tim

def center_epochs(model,toas):
    """Center PEPOCH (POSEPOCH, DMEPOCH) using min/max TOA values.

    Parameters
    ==========
    model: `pint.model.TimingModel` object
    toas: `pint.toa.TOAs` object

    Returns
    =======
    model: `pint.model.TimingModel` object
        with centered epoch(s)
    """
    midmjd=np.round((toas.get_mjds().value.max()+toas.get_mjds().value.min())/2.)
    model.change_pepoch(midmjd)

    if model.DMEPOCH.value is None:
        model.DMEPOCH.quantity = midmjd
    else:
        model.change_dmepoch(midmjd)

    if model.POSEPOCH.value is None:
        model.POSEPOCH.quantity = midmjd
    else:
        model.change_posepoch(midmjd)

    if hasattr(model, "TASC") or hasattr(model, "T0"):
        model.change_binary_epoch(midmjd)

    return model

def check_fit(fitter,skip_check=None):
    """Check that pertinent parameters are unfrozen.

    Note: process of doing this robustly for binary models is not yet automated. Checks are
    functions from par_checker.py.

    Parameters
    ==========
    fitter: `pint.fitter` object
    skip_check: list of checks to be skipped (examples: 'spin'; 'spin,astrometry')
                can be a list object or a string with comma-separated values
    """
    if skip_check:
        if type(skip_check)==str:
            skiplist = skip_check.split(',')
        else:
            skiplist = skip_check
    else:
        skiplist = []

    if 'spin' in skiplist:
        log.info("Skipping spin parameter check")
    else:
        pc.check_spin(fitter.model)

    if 'astrometry' in skiplist:
        log.info("Skipping astrometry parameter check")
    else:
        pc.check_astrometry(fitter.model)

def add_feJumps(mo,rcvrs):
    """Automatically add appropriate jumps based on receivers present

    Parameters
    ==========
    mo: `pint.model.TimingModel` object
    rcvrs: list
        receivers present in TOAs
    """
    # Might want a warning here if no jumps are necessary.
    if len(rcvrs) <= 1:
        return

    if not 'PhaseJump' in mo.components.keys():
        log.info("No frontends JUMPed.")
        log.info(f"Adding frontend JUMP {rcvrs[0]}")
        all_components = Component.component_types
        phase_jump_instance = all_components['PhaseJump']()
        mo.add_component(phase_jump_instance)

        mo.JUMP1.key = '-fe'
        mo.JUMP1.key_value = [rcvrs[0]]
        mo.JUMP1.value = 0.0
        mo.JUMP1.frozen = False

    phasejump = mo.components['PhaseJump']
    all_jumps = phasejump.get_jump_param_objects()
    jump_rcvrs = [x.key_value[0] for x in all_jumps if x.key == '-fe']
    missing_fe_jumps = list(set(rcvrs) - set(jump_rcvrs))

    if len(missing_fe_jumps):
        if len(missing_fe_jumps) == 1:
            log.info('Exactly one frontend not JUMPed.')
        else:
            log.info(f"Frontends not JUMPed: {missing_fe_jumps}...")
    else:
        log.warning("All frontends are JUMPed. One JUMP should be removed from the .par file.")
    if len(missing_fe_jumps) > 1:
        for j in missing_fe_jumps[:-1]:
            log.info(f"Adding frontend JUMP {j}")
            JUMPn = maskParameter('JUMP',key='-fe',key_value=[j],value=0.0,units=u.second)
            phasejump.add_param(JUMPn,setup=True)

def add_feDMJumps(mo,rcvrs):
    """Automatically add appropriate dmjumps based on receivers present

    Parameters
    ==========
    mo: `pint.model.TimingModel` object
    rcvrs: list
        receivers present in TOAs
    """

    if not 'DispersionJump' in mo.components.keys():
        log.info("No frontends DMJUMPed.")
        log.info(f"Adding frontend DMJUMP {rcvrs[0]}")
        all_components = Component.component_types
        dmjump_instance = all_components['DispersionJump']()
        mo.add_component(dmjump_instance)

        mo.DMJUMP1.key = '-fe'
        mo.DMJUMP1.key_value = [rcvrs[0]]
        mo.DMJUMP1.value = 0.0
        mo.DMJUMP1.frozen = False

    dmjump = mo.components['DispersionJump']
    all_dmjumps = [getattr(dmjump, param) for param in dmjump.params]
    dmjump_rcvrs = [x.key_value[0] for x in all_dmjumps if x.key == '-fe']
    missing_fe_dmjumps = list(set(rcvrs) - set(dmjump_rcvrs))

    if len(missing_fe_dmjumps):
        log.info(f"Frontends not DMJUMPed: {missing_fe_dmjumps}")
    else:
        log.info(f"All frontends are DMJUMPed.")
    if len(missing_fe_dmjumps):
        for j in missing_fe_dmjumps:
            log.info(f"Adding frontend DMJUMP {j}")
            DMJUMPn = maskParameter('DMJUMP',key='-fe',key_value=[j],value=0.0,units=u.pc*u.cm**-3)
            dmjump.add_param(DMJUMPn,setup=True)

def large_residuals(fo,threshold_us,threshold_dm=None,*,n_sigma=None,max_sigma=None,prefit=False,ignore_ASP_dms=True,print_bad=True):
    """Quick and dirty routine to find outlier residuals based on some threshold.
    Automatically deals with Wideband vs. Narrowband fitters.

    Parameters
    ==========
    fo: `pint.fitter` object
    threshold_us: float
        not a quantity, but threshold for TOA residuals larger (magnitude) than some delay in microseconds; if None, will not look at TOA residuals
    threshold_dm: float
        not a quantity, but threshold for DM residuals larger (magnitude) than some delay in pc cm**-3; if None, will not look at DM residuals
    n_sigma: float or None
        If not None, only discard TOAs and/or DMs that are at least this many sigma as well as large
    max_sigma: float or None
        If not None, also discard all TOAs and/or DMs with claimed uncertainties larger than this many microseconds
    prefit: bool
        If True, will explicitly examine the prefit residual objects in the pinter.fitter object; this will give the same result as when prefit=False but no fit has yet been performed.
    ignore_ASP_dms: bool
        If True, it will not flag/excise any TOAs from ASP or GASP data based on DM criteria
    print_bad: bool
        If True, prints bad-toa lines that can be copied directly into a yaml file

    Returns
    =======
    PINT TOA object of filtered TOAs
    """

    # check if using wideband TOAs, as this changes how to access the residuals

    if fo.is_wideband:
        is_wideband = True
        if prefit:
            time_resids = fo.resids_init.toa.time_resids.to_value(u.us)
            dm_resids = fo.resids_init.dm.resids.value
        else:
            time_resids = fo.resids.toa.time_resids.to_value(u.us)
            dm_resids = fo.resids.dm.resids.value
        dm_errors = fo.toas.get_dm_errors().value
        bes = fo.toas.get_flag_value('be')[0]  # For ignoring G/ASP DMs
        c_dm = np.zeros(len(dm_resids), dtype=bool)
    else:
        is_wideband = False
        if prefit:
            time_resids = fo.resids_init.time_resids.to_value(u.us)
        else:
            time_resids = fo.resids.time_resids.to_value(u.us)
        if threshold_dm is not None:
            log.warning('Thresholding of wideband DM measurements can only be performed with WidebandTOAFitter and wideband TOAs; threshold_dm will be ignored.')
            threshold_dm = None

    toa_errors = fo.toas.get_errors().to_value(u.us)
    c_toa = np.zeros(len(time_resids), dtype=bool)

    if threshold_us is not None:
        c_toa |= np.abs(time_resids) > threshold_us
        if n_sigma is not None:
            c_toa &= np.abs(time_resids/toa_errors) > n_sigma
        if max_sigma is not None:
            c_toa |= toa_errors > max_sigma
    if threshold_dm is not None:
        c_dm |= np.abs(dm_resids) > threshold_dm
        if n_sigma is not None:
            c_dm &= np.abs(dm_resids/dm_errors) > n_sigma
        if max_sigma is not None:
            c_dm |= dm_errors > max_sigma
        if ignore_ASP_dms:
            c_dm &= np.logical_not([be.endswith('ASP') for be in bes])
    if threshold_us is None and threshold_dm is None:
        raise ValueError("You must specify one or both of threshold_us and threshold_dm to be not None.")
    if is_wideband:
        c = c_toa | c_dm
    else:
        c = c_toa

    badlist = np.where(c)
    names = fo.toas.get_flag_value('name')[0]
    chans = fo.toas.get_flag_value('chan')[0]
    subints = fo.toas.get_flag_value('subint')[0]
    for ibad in badlist[0]:
        name = names[ibad]
        chan = chans[ibad]
        subint = subints[ibad]
        if print_bad: print(f"  - [{name}, {chan}, {subint}]")
    mask = ~c
    log.info(f'Selecting {sum(mask)} TOAs of {fo.toas.ntoas} ({sum(c)} removed) based on large_residual() criteria.')
    return fo.toas[mask]

def compare_models(fo,model_to_compare=None,verbosity='check',threshold_sigma=3.,nodmx=True):
    """Wrapper function to compare post-fit results to a user-specified comparison model.

    Parameters
    ==========
    fo: `pint.fitter` object
    model_to_compare: string or Nonetype, optional
        model to compare with the post-fit model
    verbosity: string, optional
        verbosity of output from model.compare
        options are "max", "med", "min", "check". Use ?model.compare for more info.
    threshold_sigma: float, optional
        sigma cutoff for parameter comparison
    nodmx: bool, optional
        when True, omit DMX comparison

    Returns
    =======
    str or None
        returns ascii table when verbosity is not set to "check"; also returns astropy.log statements
    """

    if model_to_compare is not None:
        comparemodel=models.get_model(model_to_compare)
    else:
        comparemodel=fo.model_init
    return comparemodel.compare(fo.model,verbosity=verbosity,nodmx=nodmx,threshold_sigma=threshold_sigma)

def remove_noise(model, noise_components=['ScaleToaError','ScaleDmError',
    'EcorrNoise','PLRedNoise']):
    """Removes noise model components from the input timing model.

    Parameters
    ==========
    model: PINT model object
    noise_components: list of model component names to remove from model
    """
    log.info('Removing pre-existing noise parameters...')
    for component in noise_components:
        if component in model.components:
            log.info(f"Removing {component} from model.")
            model.remove_component(component)
    return

def get_receivers(toas):
    """Returns a list of receivers present in the tim file(s)

    Parameters
    ==========
    toas: `pint.toa.TOAs` object

    Returns
    =======
    receivers: list of strings
        unique set of receivers present in input toas
    """
    receivers = list(set([str(f) for f in set(toas.get_flag_value('fe')[0])]))
    return receivers

def git_config_info():
    """Reports user's git config (name/email) with log.info"""
    gitname = os.popen('git config --get user.name').read().rstrip()
    gitemail = os.popen('git config --get user.email').read().rstrip()
    log.info(f'Your git config user.name is: {gitname}')
    log.info('...to change this, in a terminal: git config user.name "First Last"')
    log.info(f'Your git config user.email is: {gitemail}')
    log.info('...to change this, in a terminal: git config user.email "first.last@nanograv.org"')

def new_changelog_entry(tag, note):
    """Checks for valid tag and auto-generates entry to be copy/pasted into .yaml changelog block.

    Your NANOGrav email (before the @) and the date will be printed automatically. The "tag"
    describes the type of change, and the "note" is a short (git-commit-like) description of
    the change. Entry should be manually appended to .yaml by the user.

    Valid tags:
      - INIT: creation of the .yaml file
      - READY_FOR: indicate state of completion for release version
      - ADD or REMOVE: adding or removing a parameter
      - BINARY: change in the binary model (e.g. ELL1 -> DD)
      - NOISE: changes in noise parameters, unusual values of note
      - CURATE: notable changes in TOA excision, or adding TOAs
      - NOTE: for anything else
      - TEST: for testing!
    """
    VALID_TAGS = ['INIT','READY_FOR','ADD','REMOVE','BINARY','NOISE','CURATE','NOTE','TEST']
    vtstr = ', '.join(VALID_TAGS)
    if tag not in VALID_TAGS:
        log.error(f'{tag} is not a valid tag; valid tags are: {vtstr}.')
    else:
        # Read the git user.email from .gitconfig, return exception if not set
        stream = os.popen('git config --get user.email')
        username = stream.read().rstrip().split('@')[0]

        if not username:
            log.error('Update your git config with... git config --global user.email \"your.email@nanograv.org\"')
        else:
            # Date in YYYY-MM-DD format
            now = datetime.now()
            date = now.strftime('%Y-%m-%d')
            print(f'  - \'{date} {username} {tag}: {note}\'')

def log_notebook_to_file(source, toa_type, base_dir="."):
    """Activate logging to an autogenerated file name.

    This removes all but the first log handler, so it may behave surprisingly 
    if run multiple times not from a notebook.
    """

    if len(log.handlers)>1:
        # log.handlers[0] is the notebook output
        for h in log.handlers[1:]:
            log.removeHandler(h)
        # Start a new log file every time you reload the yaml
    log_file_name = os.path.join(
            base_dir, 
            f"{source}.{toa_type.lower()}.{time.strftime('%Y-%m-%d_%H:%M:%S')}.log")
    fh = logging.FileHandler(log_file_name)
    fh.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    log.addHandler(fh)
    

_showwarning_orig = None
def _showwarning(*args, **kwargs):
    warning = args[0]
    message = str(args[0])
    mod_path = args[2]
    # Now that we have the module's path, we look through sys.modules to
    # find the module object and thus the fully-package-specified module
    # name.  The module.__file__ is the original source file name.
    mod_name = None
    mod_path, ext = os.path.splitext(mod_path)
    for name, mod in list(sys.modules.items()):
        try:
            # Believe it or not this can fail in some cases:
            # https://github.com/astropy/astropy/issues/2671
            path = os.path.splitext(getattr(mod, '__file__', ''))[0]
        except Exception:
            continue
        if path == mod_path:
            mod_name = mod.__name__
            break
    if mod_name is not None:
        log.warning(message, extra={'origin': mod_name})
    else:
        log.warning(message)

def log_warnings():
    """Route warnings through the Astropy log mechanism.

    Astropy claims to do this but only for warnings that are subclasses of AstropyUserWarning.
    See https://github.com/astropy/astropy/issues/11500 ; if resolved there this can be simpler.
    """
    global _showwarning_orig
    if _showwarning_orig is None:
        _showwarning_orig = warnings.showwarning
        warnings.showwarning = _showwarning

def cut_summary(toas,tc,print_summary=False,donut=True,legend=True,save=False):
    """Basic summary of cut TOAs, associated reasons

    Parameters
    ==========
    toas: `pint.toa.TOAs` object
    tc: `timing_analysis.timingconfiguration.TimingConfiguration` object
    print_summary: bool, optional
        Print reasons for cuts and respective nTOA/percentages
    donut: bool, optional
        Make a donut chart showing reasons/percentages for cuts
    legend: bool, optional
        Include a legend rather than labeling slices
    save: bool, optional
        Save a png of the resulting plot.

    Returns
    =======
    cuts_dict: dict
        Cut flags and number of instances for input TOAs
    """
    import seaborn as sns
    palette = sns.color_palette("pastel",9)
    color_dict = {'dmx':palette[0],
                  'snr':palette[1],
                  'good':palette[2],
                  'badrange':palette[3],
                  'outlier10':palette[4],
                  'epochdrop':palette[5],
                  'orphaned':palette[6],
                  'maxout':palette[7],
                  'simul':palette[8],
                 }
    # gather info for title (may also be useful for other features in the future)
    tel = [t[5] for t in toas.table]
    settel = set(tel)

    fe = [str(t[6]['fe']) for t in toas.table]
    setfe = set(fe)

    mashtel = ''.join(settel)
    flavor = f"{tc.get_outfile_basename()} ({mashtel}; {', '.join(setfe)})"

    # kwarg that makes it possible to break this down by telescope/backend...?
    toa_cut_flags = [t['flags']['cut'] if 'cut' in t['flags'] else None for t in toas.orig_table]
    nTOA = len(toa_cut_flags)
    cuts_present = set(toa_cut_flags)
    cuts_dict = {}
    for c in cuts_present: 
        ncut = toa_cut_flags.count(c)
        if c: cuts_dict[c] = ncut
        else: cuts_dict['good'] = ncut
        if print_summary: print(f'{c}: {ncut} ({100*ncut/nTOA:.1f}%)')    

    nTOAcut = np.array(list(cuts_dict.values()))
    sizes = nTOAcut/nTOA
    labels = [f"{cdk} ({cuts_dict[cdk]})" for cdk in cuts_dict.keys()]
    colors = [color_dict[cdk] for cdk in cuts_dict.keys()]

    fig1, ax1 = plt.subplots()
    ax1.axis('equal')
    fig1.suptitle(flavor)
    if legend:
        ax1.pie(sizes, colors=colors, autopct='%1.1f%%', pctdistance=0.8, normalize=True)
        ax1.legend(labels,bbox_to_anchor=(0., -0.2, 1., 0.2), loc='lower left',
           ncol=3, mode="expand", borderaxespad=0.)
    else:
        ax1.pie(sizes, autopct='%1.1f%%', labels=labels, pctdistance=0.8, colors=colors, normalize=True)
    if donut:
        donut_hole=plt.Circle( (0,0), 0.6, color='white')
        p=plt.gcf()
        p.gca().add_artist(donut_hole)
    if save:
        plt.savefig(f"{mashtel}_{tc.get_outfile_basename()}_donut.png",bbox_inches='tight')
        plt.close()
    return cuts_dict
        
def display_excise_dropdowns(file_matches, toa_matches, all_YFp=False, all_GTpd=False, all_profile=False):
    """Displays dropdown boxes from which the files/plot types of interest can be chosen during manual excision. This should be run after tc.get_investigation_files(); doing so will display two lists of dropdowns (separated by bad_toa and bad_file). The user then chooses whatever combinations of files/plot types they'd like to display, and runs a cell below the dropdowns containing the read_excise_dropdowns function.
    
    Parameters
    ==========
    file_matches: a list of *.ff files matching bad files in YAML
    toa_matches: lists with *.ff files matching bad toas in YAML, bad subband #, bad subint #
    all_YFp (optional, default False): if True, defaults all plots to YFp
    all_GTpd (optional, default False): if True, defaults all plots to GTpd
    all_profile (optional, default False): if True, defaults all plots to profile vs. phase
    
    Returns (note: these are separate for now for clarity and freedom to use the subint/subband info in bad-toas)
    =======
    file_dropdowns: list of dropdown widgets containing short file names and file extension dropdowns for bad-files
    pav_file_drop: list of dropdown widget objects indicating plot type to be chosen for bad-files
    toa_dropdowns: list of dropdown widget objects containing short file names and extensions for bad-toas
    pav_toa_drop: list of dropdown widget objects indicating plot type to be chosen for bad-toas
    """
    
    ext_list = ['.ff','None','.calib','.zap']
    if all_YFp:
        pav_list = ['YFp (time vs. phase)','GTpd (frequency vs. phase)','Profile (intensity vs. phase)','None']
    elif all_GTpd:
        pav_list = ['GTpd (frequency vs. phase)','YFp (time vs. phase)','Profile (intensity vs. phase)','None']
    elif all_profile:
        pav_list = ['Profile (intensity vs. phase)','YFp (time vs. phase)','GTpd (frequency vs. phase)','None']
    else:
        pav_list = ['None','YFp (time vs. phase)','GTpd (frequency vs. phase)','Profile (intensity vs. phase)']    
   
    # Files: easy
    short_file_names = [e.split('/')[-1].rpartition('.')[0] for e in file_matches]
    file_dropdowns = [widgets.Dropdown(description=s, style={'description_width': 'initial'},
                                  options=ext_list, layout={'width': 'max-content'}) for s in short_file_names]    
    pav_file_drop = [widgets.Dropdown(options=pav_list) for s in short_file_names]
    file_output = widgets.HBox([widgets.VBox(children=file_dropdowns),widgets.VBox(children=pav_file_drop)])
    if len(file_matches) != 0:
        print('Bad-files in YAML:')
        display(file_output)
    
    # TOAs: difficult, annoying, need to worry about uniqueness
    short_toa_names = [t[0].split('/')[-1].rpartition('.')[0] for t in toa_matches]
    toa_inds = np.unique(short_toa_names, return_index=True)[1] # because np.unique sorts it
    short_toa_unique = [short_toa_names[index] for index in sorted(toa_inds)] # unique
    toa_dropdowns = [widgets.Dropdown(description=s, style={'description_width': 'initial'},
                                  options=ext_list, layout={'width': 'max-content'}) for s in short_toa_unique]
    pav_toa_drop = [widgets.Dropdown(options=pav_list) for s in short_toa_unique] 
    toa_output = widgets.HBox([widgets.VBox(children=toa_dropdowns),widgets.VBox(children=pav_toa_drop)])
    if len(toa_matches) != 0:
        print('Bad-toas in YAML:')
        display(toa_output)
    return file_dropdowns, pav_file_drop, toa_dropdowns, pav_toa_drop

def read_excise_dropdowns(select_list, pav_list, matches):
    """Reads selections for files/plots chosen via dropdown.
    
    Parameters
    ==========
    select_list: list of dropdown widget objects indicating which (if any) file extension was selected for a given matching file
    pav_list: list of dropdown widget objects indicating what type of plot was chosen
    matches: list of full paths to all matching files
    
    Returns
    =======
    plot_list: lists of full paths to files of interest and plot types chosen
    """   
    if len(matches) != 0 and isinstance(matches[0],list): # toa entries
        toa_nm = []
        toa_subband = []
        toa_subint = []
        for i in range(len(matches)):
            toa_nm.append(matches[i][0])
            toa_subband.append(matches[i][1])
            toa_subint.append(matches[i][2])
        toa_unique_ind = np.unique(toa_nm, return_index=True)[1]
        toa_nm_unique = [toa_nm[index] for index in sorted(toa_unique_ind)]
        toa_subband_unique = [toa_subband[index] for index in sorted(toa_unique_ind)]
        toa_subint_unique = [toa_subint[index] for index in sorted(toa_unique_ind)]        
    plot_list = []
    for i in range(len(select_list)):
        if (select_list[i].value != 'None') and (pav_list[i].value != 'None'):
            if isinstance(matches[0], list): # toa entries
                plot_list.append([toa_nm_unique[i].rpartition('/')[0] + '/' + select_list[i].description.split(' ')[0] + select_list[i].value, pav_list[i].value, toa_subband_unique[i], toa_subint_unique[i]])                
            else: # bad-file entries
                plot_list.append([matches[i].rpartition('/')[0] + '/' + select_list[i].description + 
                                  select_list[i].value,pav_list[i].value])
    return plot_list

def make_detective_plots(plot_list, match_list):
    """Makes pypulse plots for selected combinations of file/plot type (pav -YFp or -GTpd style).
    
    Parameters
    ==========
    plot_list: lists of full paths to files of interest and plot types chosen
    match_list: list of full paths to all matching files
    
    Returns
    =======
    None; displays plots in notebook.
    """
    for l in range(len(plot_list)):                
        if len(plot_list[l]) <= 2: # bad file entries
            if plot_list[l][1] == 'YFp (time vs. phase)':
                ar = pypulse.Archive(plot_list[l][0],prepare=True)
                ar.fscrunch()
                ar.imshow()
            elif plot_list[l][1] == 'GTpd (frequency vs. phase)':
                ar = pypulse.Archive(plot_list[l][0],prepare=True)
                ar.tscrunch()
                ar.imshow()
            elif plot_list[l][1] == 'Profile (intensity vs. phase)':
                ar = pypulse.Archive(plot_list[l][0],prepare=True)
                ar.fscrunch()
                ar.tscrunch()
                ar.plot()               
        elif len(plot_list[l]) > 2: # toa entries
            for m in range(len(match_list)):                
                if plot_list[l][0].rpartition('.')[0] in match_list[m][0]:
                    log.info(f'[Subband, subint] from bad-toa entry: [{match_list[m][1]},{match_list[m][2]}]')                    
                    if plot_list[l][1] == 'Profile (intensity vs. phase)':
                        #ar.plot(chan=match_list[m][1], subint=match_list[m][2], pol=0)
                        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12,7))
                        ar = pypulse.Archive(plot_list[l][0], prepare=True)
                        ar.plot(subint=match_list[m][2], pol=0, chan=match_list[m][1], ax=ax1, show=False)
                        ar.fscrunch()
                        ar.plot(subint=0, pol=0, chan=0, ax=ax2, show=False)
                        plt.show()
                    elif plot_list[l][1] == 'GTpd (frequency vs. phase)':
                        ar = pypulse.Archive(plot_list[l][0],prepare=True)
                        ar.tscrunch()
                        ar.imshow()
                    elif plot_list[l][1] == 'YFp (time vs. phase)':
                        ar = pypulse.Archive(plot_list[l][0],prepare=True)
                        ar.fscrunch()
                        ar.imshow()
        
        
def display_cal_dropdowns(file_matches, toa_matches):
    """ Display dropdowns for all cal files that are associated with either bad_file or bad_toa entries
    
    Parameters
    ==========
    file_matches: a list of *.ff files matching bad files in YAML
    toa_matches: lists with *.ff files matching bad toas in YAML, bad subband #, bad subint #
    """
    toa_cal_list = [i[0] for i in toa_matches]
    cal_matches = file_matches + toa_cal_list
    cal_matches_inds = np.unique(cal_matches, return_index=True)[1] # because np.unique sorts it
    cal_matches_unique = [cal_matches[index] for index in sorted(cal_matches_inds)] # unique
    cal_stem = [c.rpartition('/')[0] for c in cal_matches_unique]
    full_cal_files = []
    for c,s in zip(cal_matches_unique,cal_stem):
        hdu = fits.open(c)
        data = hdu[1].data
        hdu.close()
        calfile = data['CAL_FILE']
        full_cal_files.append(s + '/' + calfile[-1].split(' ')[-1])
    cal_plot_types = ['None','Amplitude vs. freq.','Single-axis cal sol\'n vs. freq. (pacv)','On-pulse Stokes vs. freq. (pacv -csu)']
    cal_dropdowns = [widgets.Dropdown(description=c.rpartition('/')[-1], style={'description_width': 'initial'}, options=cal_plot_types, layout={'width': 'max-content'}) for c in cal_matches_unique]
    cal_output = widgets.HBox([widgets.VBox(children=cal_dropdowns)])
    display(cal_output)
    return cal_dropdowns, full_cal_files
    
def read_plot_cal_dropdowns(cal_select_list, full_cal_files):
    """Reads selections for files/plots chosen via dropdown.
    
    Parameters
    ==========
    cal_select_list: list of dropdown widget objects indicating which (if any) cal was selected
    full_cal_files: list of all full paths to cal files
    
    Returns
    =======
    None; displays plots in notebook
    """   
    for c,f in zip(cal_select_list,full_cal_files):
        if c.value != 'None':
            if os.path.isfile(f):
                log.info(f'Making cal plot corresponding to {c.description}')
                cal_archive = pypulse.Archive(f)
                cal = cal_archive.getPulsarCalibrator()
                if c.value == 'Amplitude vs. freq.':
                    cal.plot("AB")
                elif c.value == 'Single-axis cal sol\'n vs. freq. (pacv)':
                    cal.pacv()
                elif c.value == 'On-pulse Stokes vs. freq. (pacv -csu)':
                    cal.pacv_csu()
            else:
                warn = f.rpartition('/')[-1]
                log.warning(f'{warn}: This .cf file doesn\'t seem to exist!')
            
def highlight_cut_resids(toas,model,tc_object,cuts=['badtoa','badfile'],ylim_good=True):
    """ Plot residuals vs. time, highlight specified cuts (default: badtoa/badfile) 
    
    Parameters
    ==========
    toas: `pint.toa.TOAs` object 
    model: `pint.model.TimingModel` object 
    tc_object: `timing_analysis.timingconfiguration` object
    cuts: list, optional
        cuts to highlight in residuals plot (default: manual cuts)
    ylim_good: bool, optional
        set ylim to that of uncut TOAs (default: True)
    """
    toas.table = toas.orig_table
    fo = tc_object.construct_fitter(toas,model)
    using_wideband = tc_object.get_toa_type() == 'WB'

    # get resids/errors/mjds
    if using_wideband: time_resids = fo.resids_init.residual_objs['toa'].time_resids.to_value(u.us)
    else: time_resids = fo.resids_init.time_resids.to_value(u.us)
    errs = fo.toas.get_errors().to(u.us).value
    mjds = fo.toas.get_mjds().value

    figsize = (12,3)
    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111)
    
    # find appropriate indices & plot remaining TOAs
    toa_cut_flags = np.array([t['flags']['cut'] if 'cut' in t['flags'] else None for t in toas.orig_table])
    uncut_inds = np.where(toa_cut_flags==None)[0]
    ax.errorbar(mjds[uncut_inds],time_resids[uncut_inds],yerr=errs[uncut_inds],fmt='x',alpha=0.5,color='gray')
    uncut_ylim = ax.get_ylim() # ylim for plot with good TOAs only

    import seaborn as sns
    valid_cuts = ['snr','simul','orphaned','maxout','outlier10','dmx','epochdrop','badfile','badtoa','badrange']
    sns.color_palette()
    for c in cuts:
        if c in valid_cuts:
            cut_inds = np.where(toa_cut_flags==c)[0]
            plt.errorbar(mjds[cut_inds],time_resids[cut_inds],yerr=errs[cut_inds],fmt='x',label=c)
        else:
            log.warning(f"Unrecognized cut: {c}")

    if ylim_good:
        ax.set_ylim(uncut_ylim)

    ax.grid(True)
    ax.legend(loc='upper center', bbox_to_anchor= (0.5, 1.2), ncol=len(cuts))
    plt.title(f'{model.PSR.value} highlighted cuts',y=1.2)
    ax.set_xlabel('MJD')
    ax.set_ylabel('Residual ($\mu$s)')
    
    # reset cuts for additional processing
    from timing_analysis.utils import apply_cut_select
    apply_cut_select(toas,reason='resumption after highlighting cuts')

def check_toa_version(toas):
    """ Throws a warning if TOA version does not match the version of PINT in use

    Parameters
    ==========
    toas: `pint.toa.TOAs` object
    """
    if pint.__version__ != toas.pintversion:
        log.warning(f"TOA pickle object created with an earlier version of PINT; this may cause problems.")

def check_tobs(toas,required_tobs_yrs=2.0):
    """ Throws a warning if observation timespan is insufficient

    Parameters
    ==========
    toas: `pint.toa.TOAs` object
    """
    timespan = (toas.last_MJD-toas.first_MJD).to_value('yr')
    if timespan < required_tobs_yrs:
        log.warning(f"Observation timespan ({timespan:.2f} yrs) does not meet requirements for inclusion")

def get_cut_files(toas,cut_flag):
    """ Returns set of files where cut flag is present

    Parameters
    ==========
    toas: `pint.toa.TOAs` object
    """
    toa_cut_flags = np.array([t['flags']['cut'] if 'cut' in t['flags'] else None for t in toas.orig_table])
    cut_inds = np.where(toa_cut_flags==cut_flag)[0]
    filenames = np.array([t['flags']['name'] for t in toas.orig_table])
    return set(filenames[cut_inds])
