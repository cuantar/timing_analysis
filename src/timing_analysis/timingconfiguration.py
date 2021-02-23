"""
This code contains the TimingConfiguration class, which is used to load configuration files and perform
actions, with items then passed to the notebooks.

Very basic usage:
    from timingconfiguration import TimingConfiguration
    tc = TimingConfiguration(CONFIGFILE)
"""
import io
import os
import pint.toa as toa
import pint.models as model
import pint.fitter
import numpy as np
import astropy.units as u
from astropy import log
import yaml
from timing_analysis.utils import write_if_changed
from timing_analysis.defaults import *

class TimingConfiguration:
    """
    This class contains the functionality to read
    from a configuration file and send that information
    to the timing notebooks.
    """
    def __init__(self, filename="config.yaml", tim_directory=None, par_directory=None):
        """
        Initialization method.

        Normally config files are written to be run from the root of a
        git checkout on the NANOGrav notebook server. If you want to run
        them from somewhere else, you may need to override these directories
        when you construct the TimingConfiguration object; this will not
        change what is recorded in the config file.

        Parameters
        ==========
        filename (optional) : path to the configuration file
        tim_directory (optional) : override the tim directory specified in the config
        par_directory (optional) : override the par directory specified in the config
        """
        self.filename = filename
        with open(filename) as FILE:
            self.config = yaml.load(FILE, Loader=yaml.FullLoader)
        self.tim_directory = self.config['tim-directory'] if tim_directory is None else tim_directory
        self.par_directory = self.config['par-directory'] if par_directory is None else par_directory
        self.skip_check = self.config['skip-check'] if 'skip-check' in self.config.keys() else ''

    def get_source(self):
        """ Return the source name """
        return self.config['source']

    def get_compare_model(self):
        """ Return the timing model file to compare with """
        if "compare-model" in self.config.keys() and self.config['compare-model'] is not None:
            return os.path.join(self.par_directory, self.config['compare-model'])
        return None

    def get_free_params(self, fitter):
        """Return list of free parameters"""
        if self.config["free-dmx"]:
            return self.config['free-params'] + [p for p in fitter.model.params if p.startswith("DMX_")]
        else:
            return self.config['free-params']

    def get_model_and_toas(self,usepickle=True):
        """Return the PINT model and TOA objects"""
        par_path = os.path.join(self.par_directory,self.config["timing-model"])
        toas = self.config["toas"]

        # Individual tim file
        if isinstance(toas, str):
            toas = [toas]

        BIPM = self.get_bipm()
        EPHEM = self.get_ephem()
        m = model.get_model(par_path)

        if m.PSR.value != self.get_source():
            log.warning(f'{self.filename} source entry does not match par file value ({m.PSR.value}).')

        picklefilename = os.path.basename(self.filename) + ".pickle.gz"
        # Merge toa_objects (check this works for list of length 1)
        t = toa.get_TOAs([os.path.join(self.tim_directory,t) for t in toas],
                          usepickle=usepickle,
                          bipm_version=BIPM,
                          ephem=EPHEM,
                          planets=PLANET_SHAPIRO,
                          model=m,
                          picklefilename=picklefilename)

        # Excise TOAs according to config 'ignore' block. Hard-coded for now...?
        t = self.apply_ignore(t)

        # To facilitate TOA excision, frontend/backend info
        febe_pairs = set(t.get_flag_value('f')[0])
        log.info(f'Frontend/backend pairs present in this data set: {febe_pairs}')

        return m, t

    def get_bipm(self):
        """ Return the bipm string """
        if "bipm" in self.config.keys():
            return self.config['bipm']
        return None #return some default value instead?

    def get_ephem(self):
        """ Return the ephemeris string """
        if "ephem" in self.config.keys():
            return self.config['ephem']
        return None #return some default value instead?

    def print_changelog(self):
        """Print changelog entries from .yaml in the notebook."""
        # If there's a changelog, write out its contents. If not, complain.
        if 'changelog' in self.config.keys():
            print('changelog:')
            if self.config['changelog'] is not None:
                for cl in self.config['changelog']:
                    print(f'  - {cl}')
            else:
                print('...no changelog entries currently exist.')
        else:
            print('YAML file does not include a changelog. Add \'changelog:\' and individual entries there.')

    def get_fitter(self):
        """ Return the fitter string (do more?) """
        if "fitter" in self.config.keys():
            return self.config['fitter']
        return None

    def construct_fitter(self, to, mo):
        """ Return the fitter, tracking pulse numbers if available """
        fitter_name = self.config['fitter']
        fitter_class = getattr(pint.fitter, fitter_name)
        if 'pulse_number' in to.table.columns:
            if fitter_name.startswith("Wideband"):
                return fitter_class(to, mo, additional_args=dict(toa=dict(track_mode="use_pulse_numbers")))
            else:
                return fitter_class(to, mo, track_mode="use_pulse_numbers")
        else:
            return fitter_class(to, mo)


    def get_toa_type(self):
        """ Return the toa-type string """
        if "toa-type" in self.config.keys():
            return self.config['toa-type']
        return None

    def get_niter(self):
        """ Return an integer of the number of iterations to fit """
        if "n-iterations" in self.config.keys():
            return int(self.config['n-iterations'])
        return 1

    def get_mjd_start(self):
        """Return mjd-start quantity (applies units days)"""
        if 'mjd-start' in self.config['ignore'].keys():
            return self.config['ignore']['mjd-start']*u.d
        return None

    def get_mjd_end(self):
        """Return mjd-end quantity (applies units days)"""
        if 'mjd-end' in self.config['ignore'].keys():
            return self.config['ignore']['mjd-end']*u.d
        return None

    def get_snr_cut(self):
        """ Return value of the TOA S/N cut """
        if "snr-cut" in self.config['ignore'].keys():
            return self.config['ignore']['snr-cut']
        return None #return some default value instead?

    def get_bad_epochs(self):
        """ Return list of bad epochs (basenames: [backend]_[mjd]_[source]) """
        if 'bad-epoch' in self.config['ignore'].keys():
            return self.config['ignore']['bad-epoch']
        return None

    def get_bad_ranges(self):
        """ Return list of bad epoch ranges by MJD ([MJD1,MJD2])"""
        if 'bad-range' in self.config['ignore'].keys():
            return self.config['ignore']['bad-range']
        return None

    def get_bad_toas(self):
        """ Return list of bad TOAs (lists: [filename, channel, subint]) """
        if 'bad-toa' in self.config['ignore'].keys():
            return self.config['ignore']['bad-toa']
        return None

    def get_prob_outlier(self):
        if "prob-outlier" in self.config['ignore'].keys():
            return self.config['ignore']['prob-outlier']
        return None #return some default value instead?

    def get_noise_dir(self):
        """ Return base directory for noise results """
        if 'results-dir' in self.config['noise'].keys():
            return self.config['noise']['results-dir']
        return None

    def get_ignore_dmx(self):
        """ Return ignore-dmx toggle """
        if 'ignore-dmx' in self.config['dmx'].keys():
            return self.config['dmx']['ignore-dmx']
        return None

    def get_fratio(self):
        """ Return desired frequency ratio """
        if 'fratio' in self.config['dmx'].keys():
            return self.config['dmx']['fratio']
        return FREQUENCY_RATIO

    def get_sw_delay(self):
        """ Return desired max(solar wind delay) threshold """
        if 'max-sw-delay' in self.config['dmx'].keys():
            return self.config['dmx']['max-sw-delay']
        return MAX_SOLARWIND_DELAY

    def get_custom_dmx(self):
        """ Return MJD/binning params for handling DM events, etc. """
        if 'custom-dmx' in self.config['dmx'].keys():
            return self.config['dmx']['custom-dmx']
        return None

    def apply_ignore(self,toas):
        """ Basic checks and return TOA excision info. """
        OPTIONAL_KEYS = ['mjd-start','mjd-end','snr-cut','bad-toa','bad-range','bad-epoch'] # prob-outlier, bad-ff
        EXISTING_KEYS = self.config['ignore'].keys()
        VALUED_KEYS = [k for k in EXISTING_KEYS if self.config['ignore'][k] is not None]

        # INFO?
        missing_valid = set(OPTIONAL_KEYS)-set(EXISTING_KEYS)
        if len(missing_valid):
            log.info(f'Valid TOA excision keys not present: {missing_valid}')

        invalid = set(EXISTING_KEYS) - set(OPTIONAL_KEYS)
        if len(invalid):
            log.warning(f'Invalid TOA excision keys present: {invalid}')

        valid_null = set(EXISTING_KEYS) - set(VALUED_KEYS) - invalid
        if len(valid_null):
            log.info(f'TOA excision keys included, but NOT in use: {valid_null}')

        valid_valued = set(VALUED_KEYS) - invalid
        if len(valid_valued):
            log.info(f'Valid TOA excision keys in use: {valid_valued}')

        selection = np.ones(len(toas),dtype=bool)

        # All info here about selecting various TOAs.
        if 'mjd-start' in valid_valued:
            start_select = (toas.get_mjds() > self.get_mjd_start())
            selection &= start_select
        if 'mjd-end' in valid_valued:
            end_select = (toas.get_mjds() < self.get_mjd_end())
            selection &= end_select
        if 'snr-cut' in valid_valued:
            snr_select = ((np.array(toas.get_flag_value('snr')) > self.get_snr_cut())[0])
            selection &= snr_select
            if self.get_snr_cut() > 8.0 and self.get_toa_type() == 'NB':
                log.warning('snr-cut should be set to 8; try excising TOAs using other methods.')
            if self.get_snr_cut() > 25.0 and self.get_toa_type() == 'WB':
                log.warning('snr-cut should be set to 25; try excising TOAs using other methods.')
        if 'prob-outlier' in valid_valued:
            pass
        if 'bad-ff' in valid_valued:
            pass
        if 'bad-epoch' in valid_valued:
            for be in self.get_bad_epochs():
                be_select = np.array([(be not in n) for n in toas.get_flag_value('name')[0]])
                selection *= be_select
        if 'bad-range' in valid_valued:
            for br in self.get_bad_ranges():
                min_crit = (toas.get_mjds() > br[0]*u.d)
                max_crit = (toas.get_mjds() < br[1]*u.d)
                br_select = (min_crit & max_crit)
                # Look for backend (be) flag to further refine selection, if present
                if len(br) > 2:
                    be_select = np.array([(be == br[2]) for be in toas.get_flag_value('be')[0]])
                    br_select *= be_select
                selection *= (~br_select)
        if 'bad-toa' in valid_valued:
            for bt in self.get_bad_toas():
                name,chan,subint = bt
                name_match = np.array([(n == name) for n in toas.get_flag_value('name')[0]])
                chan_match = np.array([(ch == chan) for ch in toas.get_flag_value('chan')[0]])
                subint_match = np.array([(si == subint) for si in toas.get_flag_value('subint')[0]])
                if self.get_toa_type() == 'NB':
                    bt_select = np.invert(name_match * subint_match * chan_match)
                else:
                    # don't match based on -chan flags, since WB TOAs don't have them
                    bt_select = np.invert(name_match * subint_match)
                selection &= bt_select

        log.info(f"Selecting {sum(selection)} TOAs out of {toas.ntoas} ({sum(np.logical_not(selection))} removed) based on the 'ignore' configuration block.")

        return toas[selection]
