#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import numpy as np
import astropy.units as u
from astropy import log
from pint.utils import weighted_mean
import pint.residuals as Resid
import pint.models.parameter
from pint.models import get_model
import os
import time
from subprocess import check_output, check_call, CalledProcessError
import glob
# Import some software so we have appropriate versions
import pint
import astropy
# import enterprise_extensions as e_e # NOTE - enterprise_extensions has no attribute __version__
from timing_analysis.ftester import get_fblist, param_check
import scipy.stats
import copy

ALPHA = 0.0027

def whiten_resids(fitter, restype = 'postfit'):
    """
    Function to whiten residuals. If no reddened residuals, input will be returned.

    Inputs:
    ---------
    fitter [object, dictionary]: PINT fitter class or dictionary output from ecorr_average() function.
    restype ['string']: Type of residuals, pre or post fit, to plot from fitter object. Options are:
        'prefit' - plot the prefit residuals.
        'postfit' - plot the postfit residuals (default)

    Returns:
    ---------
    wres [array]: Array of whitened timing residuals.
    """
    # Check if input is the epoch averaged dictionary, should only be used if epoch averaged NB TOAs
    if type(fitter) is dict:
        rs = fitter['time_resids']
        noise_rs = fitter['noise_resids']
        # Now check if red noise residuals
        if "pl_red_noise" in noise_rs:
            wres = rs - noise_rs['pl_red_noise']
        else:
            log.warning("No red noise, residuals already white. Returning input residuals...")
            wres = rs
    # if not assume it's a PINT fitter class object
    else:
        # Check if WB or NB
        if fitter.is_wideband:
            if restype == 'postfit':
                time_resids = fitter.resids.residual_objs['toa'].time_resids
                noise_resids = fitter.resids.noise_resids
            else:
                time_resids = fitter.resids_init.residual_objs['toa'].time_resids
                noise_resids = fitter.resids_init.noise_resids
        else:
            if restype == 'postfit':
                time_resids = fitter.resids.time_resids
                noise_resids = fitter.resids.noise_resids
            elif restype == 'prefit':
                time_resids = fitter.resids_init.time_resids
                noise_resids = fitter.resids_init.noise_resids
            else:
                raise ValueError("Unrecognized residual type: %s. Please choose from 'prefit' or 'postfit'."%(restype))
            # Get number of residuals
        num_res = len(time_resids)
        # Check that the key is in the dictionary
        if "pl_red_noise" in noise_resids:
            wres = time_resids - noise_resids['pl_red_noise'][:num_res]
        else:
            log.warning("No red noise, residuals already white. Returning input residuals...")
            wres = time_resids
    return wres

def rms_by_backend(resids, errors, rcvr_backends, dm = False):
    """
    Function to take a fitter, list of residuals errors, and backends and compute the rms and weighted rms
    for either time residuals or DM residuals if a wideband residuals.

    Inputs:
    ----------
    resids [list]: List of residuals.
    errors [list]: List of residual errors.
    rcvr_backends [list]: List of backends.
    dm [boolean]: If True, will do computation with DM residuals [defaut: False].
    
    Returns:
    ----------
    rs_dict [dictionary]: Dictionary of rms and wieghted rms residuals for each backend-reciever combination.
    """
    # Define output dictionary
    rs_dict = {}
    # Get RMS of all residuals
    # Now loop through and compute on a per receiver-backend status
    RCVR_BCKNDS = np.sort(list(set(rcvr_backends)))
    if dm:
        avg_RMS_ALL = np.std(resids)
        # Get the weighted rms of averaged residuals
        weights = 1.0 / (errors ** 2)
        wmean, werr, wsdev = weighted_mean(resids, weights, sdev=True)
        avg_WRMS_ALL = wsdev
        # Add to dictionary
        rs_dict['All'] = {'rms':avg_RMS_ALL, 'wrms':avg_WRMS_ALL}
        for r_b in RCVR_BCKNDS:
            # Get indices of receiver-backend toas
            inds = np.where(rcvr_backends==r_b)[0]
            # Select them
            rms = np.std(resids[inds])
            weights = 1.0 / (errors ** 2)
            wmean, werr, wsdev = weighted_mean(resids[inds], weights[inds], sdev=True)
            wrms = wsdev
            rs_dict[r_b] = {'rms':rms, 'wrms':wrms}
    else:
        avg_RMS_ALL = np.std(resids).to(u.us)
        # Get the weighted rms of averaged residuals
        weights = 1.0 / (errors.to(u.s) ** 2)
        wmean, werr, wsdev = weighted_mean(resids, weights, sdev=True)
        avg_WRMS_ALL = wsdev.to(u.us)
        # Add to dictionary
        rs_dict['All'] = {'rms':avg_RMS_ALL, 'wrms':avg_WRMS_ALL}
        for r_b in RCVR_BCKNDS:
            # Get indices of receiver-backend toas
            inds = np.where(rcvr_backends==r_b)[0]
            # Select them
            rms = np.std(resids[inds].to(u.us))
            weights = 1.0 / (errors.to(u.s) ** 2)
            wmean, werr, wsdev = weighted_mean(resids[inds], weights[inds], sdev=True)
            wrms = wsdev.to(u.us)
            rs_dict[r_b] = {'rms':rms, 'wrms':wrms}
    # return the dictionary
    return rs_dict


def resid_stats(fitter, epoch_avg = False, whitened = False, dm_stats = False, print_pretty = False):
    """
    Function to get statistics for the residuals. This includes the RMS and WRMS for all residuals, as well as
    per-backend. Option for epoch averaged or not epoch averaged. If dm_stats are also returned, then there
    will be a second output dictionary for the DM stats by receiver-backend combo.

    Inputs:
    ----------
    fitter [object]: PINT fitter class object, post-fit.
    epoch_avg [boolean]: If True, will output stats for epoch averaged residulas, else will be for 
        non-epoch averaged residuals [default: False].
    whitened [boolean]: If True, will output stats for whitened residulas, else will be for 
        non-whitened residuals [default: False].
    dm_stats [boolean]: If True, will also output the stats for the DM residuals for wideband fitters.
        Note this will return an additional dictionary, dm_stats [default: False].
    print_pretty [boolean]: If True, will nicely print the W/RMS per receiver-backend combo [default: False].

    Returns:
    ----------
    rs_dict [nested dictionary]:

        First set of keys are Receiver-Backend combos, e.g. L-wide_ASP, S-wide_PUPPI. For the W/RMS of all residuals,
        the key is 'All'.

        Within each Receiver-Backend combo the flags are:
            rms [astropy quantity: rms of the residuals for the receiver-backend combo in microseconds.
            wrms [astropy quantity: weighted rms of the residuals for the receiver-backend combo in microseconds.
     
    dm_dict [nested dictionary]: Same as rs_dict but for DM residuals with unit of pc cm^-3.
    """
    # Check if fitter is WB or not
    if fitter.is_wideband:
        resids = fitter.resids.residual_objs['toa']
        dm_resids = fitter.resids.residual_objs['dm']
        NB = False
        if epoch_avg:
            log.warning("Warning, cannot epoch average wideband residuals, will skip epoch averaging.")
    else:
        resids = fitter.resids
        NB = True

    # get rcvr backend combos for averaged residuals
    rcvr_bcknds = np.array(resids.toas.get_flag_value('f')[0])

    # Compute epoch averaged stats
    if epoch_avg and NB:
        avg = fitter.resids.ecorr_average(use_noise_model=True)
        avg_rcvr_bcknds = []
        for iis in avg['indices']:
            avg_rcvr_bcknds.append(rcvr_bcknds[iis[0]])
        avg_rcvr_bcknds = np.array(avg_rcvr_bcknds)
        # compute averaged, whitened
        if whitened:
            wres_avg = whiten_resids(avg)
            rs_dict = rms_by_backend(wres_avg.to(u.us), avg['errors'], avg_rcvr_bcknds)
        # compute averaged
        else:
            rs_dict = rms_by_backend(avg['time_resids'], avg['errors'], avg_rcvr_bcknds)

    # Compute whitened
    elif whitened:
        wres = whiten_resids(fitter)
        #rs_dict = rms_by_backend(wres.to(u.us), fitter.toas.get_errors(), rcvr_bcknds)
        rs_dict = rms_by_backend(wres.to(u.us), resids.get_data_error(), rcvr_bcknds)

    # If not averaged or whitened, compute with functions that already exist
    if not epoch_avg and not whitened:
        # Define dictionary for return values
        rs_dict = {}
        # Get total RMS and WRMS
        RMS_ALL = resids.time_resids.std().to(u.us) # astropy quantity
        WRMS_ALL = resids.rms_weighted() # astropy quantity, units are us

        # Now split up by backend
        RCVR_BCKNDS = np.sort(list(set(rcvr_bcknds)))
        # Turn into dictionary to return
        rs_dict['All'] = {'rms':RMS_ALL, 'wrms':WRMS_ALL}
        for r_b in RCVR_BCKNDS:
            # Get indices of receiver-backend toas
            inds = np.where(rcvr_bcknds==r_b)[0]
            # Select them
            fitter.toas.select(inds)
            # Create new residual object
            r = Resid.Residuals(fitter.toas, fitter.model)
            # Get new RMS, WRMS
            rs_dict[r_b] = {'rms':r.time_resids.std().to(u.us), 'wrms':r.rms_weighted()}
            # Unselect them
            fitter.toas.unselect()

    # print output if desired
    if print_pretty:
        rs_keys = rs_dict.keys()
        for k in rs_keys:
            l = "# WRMS(%s) = %.3f %s" %(k, rs_dict[k]['wrms'].value, rs_dict[k]['wrms'].unit)
            print(l)
            l = "#  RMS(%s) = %.3f %s" %(k, rs_dict[k]['rms'].value, rs_dict[k]['rms'].unit)
            print(l)

    # Check if dm stats are desired
    if dm_stats:
        if not NB:
            dm_dict = rms_by_backend(dm_resids.resids, dm_resids.get_data_error(), rcvr_bcknds, dm = True)
            if print_pretty:
                print()
                dm_keys = dm_dict.keys()
                for k in rs_keys:
                    l = "# WRMS(%s) = %.6f %s" %(k, dm_dict[k]['wrms'].value, dm_dict[k]['wrms'].unit)
                    print(l)
                    l = "#  RMS(%s) = %.6f %s" %(k, dm_dict[k]['rms'].value, dm_dict[k]['rms'].unit)
                    print(l)
        else:
            log.warning("Cannot compute DM Stats, not Wideband timing data.")

    # Return the dictionary
    if dm_stats and not NB:
        return rs_dict, dm_dict
    else:
        return rs_dict



# Define helper functions
def year(mjd):
    """
    Calculate the year from an MJD.
    
    Inputs:
    ---------
    mjd [float]: MJD value.
    
    Returns:
    ---------
    year [float]: MJD value converted to a year.
    """
    return (mjd - 51544.0)/365.25 + 2000.0


def report_ptest(label, ftest_dict = None, alpha=ALPHA):
    """
    Nicely prints the results of F-tests in a human-readable format.
    
    Input:
    --------
    label [string]: Name of the parameter(s) that were added/removed for the F-test.
    ftest_dict [dictionary]: Dictionary of output values from the PINT `ftest()` function. If `None`, will
        print a line of NaNs for each reported value.
    alpha [float]: Value to compare for F-statistic significance. If the F-statistic is lower than alpha, 
        the timing model parameters are deemed statistically significant to the timing model.
    """
    # If F-test fails, print line of NaNs
    if ftest_dict == None:
        line = "%42s %7.3f %9.2f %5f %.3f" % (label, np.nan, np.nan, np.nan, np.nan)
    # Else print the computed values
    else:
        # Get values from input dictionary
        rms = ftest_dict['resid_wrms_test'].value # weighted root mean square of timing residuals
        chi2 = ftest_dict['chi2_test'] # chi-squared value of the fit of the F-tested model
        ndof = ftest_dict['dof_test'] # number of degrees of freedom in the F-tested model
        if "dm_resid_wrms_test" in ftest_dict.keys():
            dmrms = ftest_dict['dm_resid_wrms_test'].value # weighted root mean square of DM residuals
        else:
            dmrms = None
        Fstatistic=  ftest_dict['ft'] # F-statistic from the F-test comparison
        if Fstatistic is None:
            if dmrms != None:
                line = "%42s %7.3f %16.6f %9.2f %5d --" % (label, rms, dmrms, chi2, ndof)
            else:
                line = "%42s %7.3f %9.2f %5d --" % (label, rms, chi2, ndof)
        elif Fstatistic:
            if dmrms != None:
                line = "%42s %7.3f %16.6f %9.2f %5d %.3g" % (label, rms, dmrms, chi2, ndof, Fstatistic)
            else:
                line = "%42s %7.3f %9.2f %5d %.3g" % (label, rms, chi2, ndof, Fstatistic)
            if Fstatistic < alpha:
                line += " ***"
        else:
            if dmrms != None:
                line = "%42s %7.3f %16.6f %9.2f %5d xxx" % (label, rms, dmrms, chi2, ndof)
            else:
                line = "%42s %7.3f %9.2f %5d xxx" % (label, rms, chi2, ndof)
    return line


def get_Ftest_lines(Ftest_dict, fitter, alpha = ALPHA):
    """
    Function to get nicely formatted lines from F-test dictionary.

    Input:
    ----------
    Ftest_dict [dictionary]: Dictionary of F-test results output by the `run_Ftests()` function.
    fitter [object]: The PINT fitter object.
    
    Returns:
    ----------
    ftest_lines [list]: List of nicely formatted F-test results lines to be printed elsewhere.
    """
    ftest_lines = []
    cur_fd = [param for param in fitter.model.params if "FD" in param]
    for fk in Ftest_dict.keys():
        # Get the FB parameter lines
        if 'FB' in fk:
            # Get the value of fbmax, note, may need fixes somewhere
            try:
                fbmax = (int(max(Ftest_dict[fk].keys())[-1]))
            except:
                fbmax = (int(max(Ftest_dict[fk].keys())[-2]))
            fblist = get_fblist(fitter)
            fbused = (len(fblist)>0)
            fbp = [fblist[ifb] for ifb in sorted(fblist.keys())]  # sorted list of fb parameters
            ftest_lines.append("\nTesting FB parameters, present list: "+" ".join(fbp))
            ftest_lines.append("\nTesting removal of FB parameters:")
            for i in range(1,len(fblist)):
                p = [fbp[j] for j in range(i,len(fbp))]
                ffk = 'FB%s+'%i
                l = report_ptest(" ".join(p), Ftest_dict[fk][ffk], alpha = alpha)
                ftest_lines.append(l)
            ftest_lines.append("Testing addition of FB parameters:")
            for i in range(len(fblist),fbmax+1):
                p = ["FB%d" % (j) for j in range(len(fblist),i+1)]
                ffk = 'FB%s'%i
                l = report_ptest(" ".join(p), Ftest_dict[fk][ffk], alpha = alpha)
                ftest_lines.append(l)
        # Report the intial values        
        elif 'initial' in fk:
            l = report_ptest(fk, Ftest_dict[fk])
            ftest_lines.append(l)
        # Report any added F-tested parameters, including FD
        elif "Add" in fk:
            ftest_lines.append('Testing additional parameters:')
            for ffk in Ftest_dict[fk].keys():
                if ffk == 'Binary':
                    for fffk in Ftest_dict[fk][ffk].keys():
                        l = report_ptest(fffk, Ftest_dict[fk][ffk][fffk], alpha = alpha)
                        ftest_lines.append(l)
                elif 'FD' in ffk:
                    ftest_lines.append("\nTesting adding FD terms (%s enabled):" % (cur_fd))
                    for fffk in Ftest_dict[fk][ffk].keys():
                        l = report_ptest(fffk, Ftest_dict[fk][ffk][fffk], alpha = alpha)
                        ftest_lines.append(l)
                else:
                    l = report_ptest(ffk, Ftest_dict[fk][ffk], alpha = alpha)
                    ftest_lines.append(l)
        # Report any removed F-tested parameters, including FD 
        elif "Remove" in fk:
            ftest_lines.append('\nTesting removal of parameters:')
            for ffk in Ftest_dict[fk].keys():
                if ffk == 'Binary':
                    for fffk in Ftest_dict[fk][ffk].keys():
                        l = report_ptest(fffk, Ftest_dict[fk][ffk][fffk], alpha = alpha)
                        ftest_lines.append(l)
                elif 'FD' in ffk:
                    ftest_lines.append("\nTesting removing FD terms (%s enabled):" % (cur_fd))
                    for fffk in Ftest_dict[fk][ffk].keys():
                        l = report_ptest(fffk, Ftest_dict[fk][ffk][fffk], alpha = alpha)
                        ftest_lines.append(l)
                else:
                    l = report_ptest(ffk, Ftest_dict[fk][ffk], alpha = alpha)
                    ftest_lines.append(l)
                    
        elif fk == 'F':
            # Get current number of spin frequency derivatives
            current_freq_deriv = 1
            for i in range(2,21):
                p = "F%d" % i
                if p in fitter.model.params:
                    current_freq_deriv = i
            ftest_lines.append("Testing spin freq derivs (%s enabled):" % (current_freq_deriv))
            for ffk in Ftest_dict[fk].keys():
                l = report_ptest(ffk, Ftest_dict[fk][ffk], alpha = alpha)
                ftest_lines.append(l)

    return ftest_lines


def pdf_writer(fitter, 
               parfile, 
               rs_dict, 
               Ftest_dict=None, 
               dm_dict=None, 
               append=None, 
               previous_parfile=None, 
               fitter_noise=None):
    """Take output from timing notebook functions and write things out nicely in a summary pdf.

    Input
    -----
    fitter [pint.fitter.Fitter]: Fitter used for initial fit.
    parfile [string]: Name of parfile used to generate residuals.
    rs_dict [dictionary]: Dictionary of residual stats output by the `resid_stats()` function.
    Ftest_dict [dictionary]: Dictionary of F-test results output by the `run_Ftests()` function.
    dm_dict [dictionary]: Optional dictionary of DM residual stats output by the `resid_stats()` function for WB timing.
        Input is optional. if `None` will not write out the DM residual stats [default: None].
    append [string or None]: default is `None`, else should be a string to the path to the texfile to append output to.
    previous_parfile [string or None]: If provided, report a comparison with this par file (presumably from a previous release).
    fitter_noise [pint.fitter.Fitter]: Fitter that has had new noise parameters applied (if available).
    """
    def verb(s):
        s = str(s).strip()
        if "\n" in s:
            return "\n".join(verb(p) for p in s.split("\n"))
        for c in "@|!%":
            if c not in s:
                return r'\verb' + c + s + c
        else:
            raise ValueError(f"String {s} contains all my known verbatim quoting characters")
    
    # Check if fitter is wideband or not
    if fitter.is_wideband:
        NB = False
        resids = fitter.resids.residual_objs['toa']
        dm_resids = fitter.resids.residual_objs['dm']
    else:
        NB = True
        resids = fitter.resids
    
    # Start the latex pdf text (from old finalize timing script)
    psr = fitter.model.PSR.value.replace('-','$-$')
    write_header = True
    if append != None:
        texfile = append
        if os.path.exists(texfile):
            write_header = False
        fsum = open(texfile,'a')
    else:
        if NB:
            texfile = fitter.model.PSR.value + '.summary.nb.tex'
        else:
            texfile = fitter.model.PSR.value + '.summary.wb.tex'
        fsum = open(texfile,'w')
    
    if write_header:
        fsum.write(r'\documentclass[11pt]{article}' + '\n')
        fsum.write(r'\usepackage[T1]{fontenc}' + '\n')
        fsum.write(r'\usepackage[utf8]{inputenc}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{D7}{$\times$}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{B9}{\textsuperscript{1}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{B2}{\textsuperscript{2}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{B3}{\textsuperscript{3}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{207B}{\textsuperscript{-}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2070}{\textsuperscript{0}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2071}{\textsuperscript{1}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2072}{\textsuperscript{2}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2073}{\textsuperscript{3}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2074}{\textsuperscript{4}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2075}{\textsuperscript{5}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2076}{\textsuperscript{6}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2077}{\textsuperscript{7}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2078}{\textsuperscript{8}}' + '\n')
        fsum.write(r'\DeclareUnicodeCharacter{2079}{\textsuperscript{9}}' + '\n')
        fsum.write(r'\usepackage{graphicx}' + '\n')
        fsum.write(r'\addtolength{\hoffset}{-2.5cm}' + '\n')
        fsum.write(r'\addtolength{\textwidth}{5.0cm}' + '\n')
        fsum.write(r'\addtolength{\voffset}{-2.5cm}' + '\n')
        fsum.write(r'\addtolength{\textheight}{5.0cm}' + '\n')
        fsum.write(r'\usepackage{fancyhdr}' + '\n')
        fsum.write(r'\pagestyle{fancy}' + '\n')
        fsum.write(r'\lhead{\leftmark}' + '\n')
        fsum.write(r'\rhead{\thepage}' + '\n')
        fsum.write(r'\cfoot{}' + '\n')
        fsum.write(r'\begin{document}' + '\n')
    else:
        fsum.write(r'\clearpage' + '\n')
        fsum.write(r'\newpage' + '\n')

    # Get some values from the fitter
    start = fitter.toas.first_MJD.value
    finish = fitter.toas.last_MJD.value
    span = finish - start

    label = f"{psr} {'narrowband' if NB else 'wideband'}"
    # Write beginning header info
    fsum.write(r'\section*{PSR ' + label + '\markboth{' + label + '}{}}\n')
    
    try:
        who = check_output(['git','config','--get','user.name'], text=True).strip()
    except CalledProcessError:
        who = "anonymous user"

    when = time.strftime("%Y %b %d (%a) %H:%M:%S GMT", time.gmtime())
    fsum.write(f'Summary generated on {when} by {who}' + r'\\' + '\n')
    # print par file
    fsum.write(r'Input par file: ' + verb(parfile) + r'\\' + '\n')
    # print tim file directory
    rls_dir = fitter.toas.filename[0].rpartition('/')[0]
    fsum.write(r'Input tim file directory: ' + verb(rls_dir) + r'\\' + '\n')
    # print list of tim file names, limit two tim files per line
    fsum.write(r'Input tim files:' + "\n")
    fsum.write(r'\begin{itemize}' + "\n")
    for tf in fitter.toas.filename:
        fsum.write(r'\item ' + verb(tf.split('/')[-1]) + '\n')
    fsum.write(r'\end{itemize}' + "\n")
    fsum.write('Span: %.1f years (%.1f -- %.1f)\\\\\n ' % (span/365.24,
        year(float(start)), year(float(finish))))

    if NB:
        try:
            avg_dict = fitter.resids.ecorr_average(use_noise_model=True)
            mjdlist = np.sort(avg_dict['mjds'].value)
        except:
            log.warning("Cannot get epoch averaged residual MJDs, Epoch calculation will use all MJDs and may not be correct.")
            mjdlist = np.sort(fitter.toas.get_mjds().value)
    else:
        mjdlist = np.sort(fitter.toas.get_mjds().value)
    maxepoch = 6.5
    nepoch = 1
    m0 = mjdlist[0]
    for m in mjdlist:
        if m > m0+maxepoch:
            nepoch += 1
            m0 = m
    fsum.write('Epochs (defined as observations within %.1f-day spans): %d\\\\\n' % (maxepoch,nepoch))

    # Print what fitter was used:
    fsum.write('Wideband data: %s\n' %('No' if NB else 'Yes'))
    fsum.write('\\\\Fitter: %s\n' %(fitter.__class__.__name__))

    model = get_model(parfile)
    # Write out the timing model
    fsum.write(r'\subsection*{Timing model}' + '\n')
    fsum.write(r'\begin{verbatim}' + '\n')
    # Get the parfile lines
    parlines = model.as_parfile().split('\n')
    for l in parlines:
        if l.startswith('DMX'): continue
        fsum.write(l+"\n")
    fsum.write(r'\end{verbatim}' + '\n')

    # Write out the residual stats
    fsum.write(r'\subsection*{Residual stats}' + '\n')
    fsum.write(r'\begin{verbatim}' + '\n')
    rs_keys = rs_dict.keys()
    for k in rs_keys:
        l = "# WRMS(%s) = %.3f %s" %(k, rs_dict[k]['wrms'].value, rs_dict[k]['wrms'].unit)
        fsum.write(l + '\n')
        l = "#  RMS(%s) = %.3f %s" %(k, rs_dict[k]['rms'].value, rs_dict[k]['rms'].unit)
        fsum.write(l + '\n\n')
    fsum.write(r'\end{verbatim}' + '\n')

    # Write out DM residual stats if desired
    if not NB and dm_dict != None:
        fsum.write(r'\subsection*{DM Residual stats}' + '\n')
        fsum.write(r'\begin{verbatim}' + '\n')
        rs_keys = rs_dict.keys()
        for k in rs_keys:
            l = "# WRMS(%s) = %.6f %s" %(k, dm_dict[k]['wrms'].value, dm_dict[k]['wrms'].unit)
            fsum.write(l + '\n')
            l = "#  RMS(%s) = %.6f %s" %(k, dm_dict[k]['rms'].value, dm_dict[k]['rms'].unit)
            fsum.write(l + '\n\n')
        fsum.write(r'\end{verbatim}' + '\n')

    # Check pulsar name
    fsum.write(r'\subsection*{Pulsar name check in .par file}' + '\n')
    fsum.write('Name in .par file: %s\\\\\n' % (model.PSR.value))
    if model.PSR.value.startswith("B") or model.PSR.value.startswith("J"):
        fsum.write('OK: starts with B or J\\\\\n')
    else:
        fsum.write('Warning: does not start with B or J\\\\\n')
    if not os.path.basename(parfile).startswith(model.PSR.value):
        msg = f'Warning: parfile is called {verb(parfile)} but pulsar name is {model.PSR.value}'
        fsum.write(msg + r"\\" + "\n")
    fsum.write("\n")
    
    # Write Epochs section
    fsum.write(r'\subsection*{Epochs near center of data span?}' + '\n')
    tmidspan = 0.5*(float(finish)+float(start))
    fsum.write('Middle of data span: midspan = %.2f\\\\\n' % (tmidspan))
    dtpepoch = float(model.PEPOCH.value)-tmidspan
    fsum.write('PEPOCH - midspan = $%.2f$ days = $%.2f$ years\\\\\n'  % ( dtpepoch, dtpepoch/365.24))
    if param_check('TASC', fitter, check_enabled=True):
        dttasc = float(model.TASC.value)-tmidspan
        fsum.write('TASC - midspan = $%.2f$ days = $%.1f$ years\\\\\n'  % ( dttasc, dttasc/365.24))
    if param_check('T0', fitter, check_enabled=True):
        dtt0 = float(model.T0.value)-tmidspan
        fsum.write('TASC - midspan = $%.2f$ days = $%.1f$ years\\\\\n'  % ( dtt0, dtt0/365.24))
    fsum.write('\n')

    # Check for more than one jumped receiver
    fsum.write(r'\subsection*{Receivers and JUMPs}' + '\n')
    groups = set(np.array(resids.toas.get_flag_value('f')[0]))
    receivers = set([g.replace("_GUPPI","").replace("_GASP","").replace("_PUPPI","").replace("_ASP","") for g in groups])
    jumped = []
    for p in model.params:
        if "JUMP" in p and "DM" not in p:
            jumped.append(getattr(model, p).key_value[0])
    if len(jumped)==0:
        log.warning("no JUMPs")
        jumped = ()
    nnotjumped = 0
    fsum.write('{\\setlength{\\topsep}{6pt}%\n\\setlength{\\partopsep}{0pt}%\n')  # starts a new environment
    fsum.write('\\begin{tabbing}\\hspace*{72pt}\\=\\kill\n')
    fsum.write('Receivers:\\\\[4pt]')
    for r in receivers:
        fsum.write('\n')
        fsum.write(r.replace("_","\\_"))
        if r in jumped:
            fsum.write('\\> JUMP')
        else:
            nnotjumped += 1
        fsum.write('\\\\')
    if len(receivers)>0:
        fsum.write('[4pt]')
    if nnotjumped==1:
        fsum.write('One non-JUMPed receiver.  Good.\\\\')
    else:
        fsum.write('Warning: %d non-JUMPed receivers.\\\\' % (nnotjumped,))
    fsum.write('\end{tabbing}\n')
    fsum.write('}\n\n')   # ends environment started above.

    fsum.write(r'\subsection*{Frozen parameters all zero?}' + '\n')
    any_dodgy = False
    ignoring = []
    for p in model.params_ordered:
        pm = getattr(model, p)
        if (isinstance(pm, (pint.models.parameter.floatParameter, 
                            pint.models.parameter.maskParameter,
                            pint.models.parameter.MJDParameter,
                            pint.models.parameter.AngleParameter,
                           )) 
            and pm.frozen
            and pm.value is not None
            and pm.value != 0):
            if p in {"START", "FINISH", "POSEPOCH", "DMEPOCH", "PEPOCH", "TZRMJD", "DM", "DMX", "NTOA", "CHI2", "DMDATA", "TZRFRQ"}:
                ignoring.append(p)
                continue
            skip = False
            for pfx in ["EFAC", "EQUAD", "TN", "ECORR", "DMEFAC", "DMEQUAD"]:
                if p.startswith(pfx):
                    ignoring.append(p)
                    skip = True
                    break
            if skip:
                continue
            any_dodgy = True
            fsum.write(f"Parameter {verb(p)} is frozen at {pm.value}\\\\\n")
    if ignoring:
        w = ', '.join([verb(i) for i in ignoring])
        fsum.write(f"Ignoring {w}\\\\\n")
    if not any_dodgy:
        fsum.write("Yes.\\\\\n")

    fsum.write(r'\subsection*{par file fully fit?}' + '\n')
    chi2_initial = fitter.resids_init.chi2
    chi2_final = fitter.resids.chi2
    chi2_decrease = chi2_initial-chi2_final
    fsum.write(f"par file initial $\\chi^2$: {chi2_initial}\\\\\n")
    fsum.write(f"par file final $\\chi^2$: {chi2_final}\\\\\n")
    fsum.write(f"Decrease: {chi2_decrease}\\\\\n")
    if abs(chi2_decrease) > 0.01:
        if chi2_decrease > 0:
            msg = f"par file $\\chi^2$ decreased by {chi2_decrease} during fitting, fitter has not fully converged"
        else:
            msg = f"par file $\\chi^2$ increased by {-chi2_decrease} during fitting, fitter has produced bogus result"
        log.warning(msg)
        fsum.write(f'\\\\ Warning: {msg}\\\\\n')
    else:
        fsum.write(f'\\\\ Fitting produces no major change, all is probably fine.\\\\\n')
    sigma_threshold = 0.1
    max_cs = 0
    changed = None
    for p in fitter.model.free_params:
        # FIXME: replicate compare_model here? run compare_model? maybe with low verbosity but capture log messages?
        pm = getattr(fitter.model, p)
        iv = getattr(fitter.model_init, p).value
        fv = pm.value
        u = pm.uncertainty.value
        cs = (iv-fv)/u
        if abs(cs) >= abs(max_cs):
            max_cs = cs
            changed = p
        if abs(cs) > sigma_threshold:
            msg = f"parameter {verb(p)} changed from {iv} to {fv} ({cs:.2g} sigma) during fit."
            log.warn(msg)
            fsum.write("WARNING: " + msg + "\\\\\n")
    fsum.write(f"Largest parameter change during fit was {verb(changed)} by {max_cs:.2g} sigma.\\\\\n")
                   
    # Write out if reduced chi squared is close to 1
    fsum.write(r'\subsection*{Reduced $\chi^2$ close to 1.00?}' + '\n')
    chi2_0 = fitter.resids_init.chi2
    ndof_0 = fitter.resids_init.dof
    rchi= chi2_0/ndof_0
    fpp = scipy.stats.chi2(int(ndof_0)).sf(float(chi2_0))
    fsum.write('Reduced $\chi^2$ is %f/%d = %f (false positive probability %g)\n' % (chi2_0,ndof_0,rchi,fpp))
    if rchi<0.95 or rchi>1.05:
        # Eh. Not clear if this is useful given an FPP.
        fsum.write('\\\\ Warning: $\chi^2$ is far from 1.00\n')
    if 0.001<fpp<0.999:
        fsum.write('\\\\ False positive probability is believable\n')
    else:
        log.warning(f"Reduced chi-squared of {rchi} has unlikely false positive probability of {fpp}") 
        fsum.write('\\\\ Warning: False positive probability not believable\n')
    if fitter_noise is not None:
        fsum.write("\\\\\n")
        fsum.write("\\\\\n")
        fsum.write("After applying new noise model:\\\\\n")
        chi2_1 = fitter_noise.resids.chi2
        ndof_1 = fitter_noise.resids.dof
        rchi = chi2_1/ndof_1
        fpp = scipy.stats.chi2(int(ndof_1)).sf(float(chi2_1))
        fsum.write('New reduced $\chi^2$ is %f/%d = %f (false positive probability %g)\n' % (chi2_1,ndof_1,rchi,fpp))
        if 0.001<fpp<0.999:
            fsum.write('\\\\ New false positive probability is believable\n')
        else:
            log.warning(f"New reduced chi-squared of {rchi} has unlikely false positive probability of {fpp}") 
            fsum.write('\\\\ Warning: New false positive probability not believable\n')

    # Check EFACs, EQUADs, ECORRs:
    fsum.write(r'\subsection*{Error parameters reasonable?}' + '\n')
    any_bad_efac = []
    fsum.write(r"\begin{tabular}{l c}" + "\n")
    fsum.write(r"Parameter & value\\" + "\n")
    for p in sorted(model.params):
        pm = getattr(model, p)
        if p.startswith("EFAC") or p.startswith("DMEFAC"):
            val = f"{pm.value:.3f}"
            if not 0.8 < pm.value < 1.2:
                val = r"\textbf{" + val + "}"
                any_bad_efac.append(p)
            fsum.write(verb(f"{p} {pm.key} {pm.key_value[0]}") + f" & {val}\\\\\n")
    fsum.write(r"\end{tabular}\\" + "\n")    
    if any_bad_efac:
        msg = f"Some EFACs seem very large or small, has something gone wrong? {', '.join(verb(e) for e in any_bad_efac)}"
        fsum.write(msg + "\\\\\n")
        log.warning(msg)
    else:
        fsum.write("All EFACs seem reasonable.\\\\\n")
    fsum.write("\n")
    fsum.write(r"\begin{tabular}{l c c c}" + "\n")
    fsum.write(r"Parameter & value & TOA median & ratio\\" + "\n")
    for p in sorted(model.params):
        pm = getattr(model, p)
        if p.startswith("EQUAD") or p.startswith("ECORR"):
            unc = np.median(fitter.toas.table["error"][pm.select_toa_mask(fitter.toas)])
            ratio = pm.value/unc
            if ratio>0.75:
                r = r"\textbf{"+f"{ratio:.2f}"+"}"
            else:
                r = f"{ratio:.2f}"
            fsum.write(verb(f"{p} {pm.key} {pm.key_value[0]}") + f" & {pm.value:.3f} $\\mu$s & "
                       f"{unc:.3f} $\\mu$s & {r}" + "\\\\\n")
        if p.startswith("DMEQUAD"):
            unc = np.median(fitter.toas.get_dm_errors().to_value(pint.dmu)[pm.select_toa_mask(fitter.toas)])
            ratio = pm.value/unc
            if ratio>0.75:
                r = r"\textbf{"+f"{ratio:.2f}"+"}"
            else:
                r = f"{ratio:.2f}"
            fsum.write(verb(f"{p} {pm.key} {pm.key_value[0]}") + f" & {pm.value:.3g} dmu & "
                       f"{unc:.3g} dmu & {r}" + "\\\\\n")
    fsum.write(r"\end{tabular}\\" + "\n")
    fsum.write("EQUADs and DMEQUADs that are large compared to the uncertainties on the "
               "relevant TOAs may be a sign of something strange.\\\\\n")
    
    fsum.write(r'\subsection*{Error parameters agree with chains?}' + '\n')
    if fitter_noise is None:
        fsum.write("\n")
        fsum.write("Noise chains not available.\\\\\n")
    else:
        any_bogus = False
        fsum.write(r"\begin{tabular}{l c c c c}" + "\n")
        fsum.write(r"Parameter & par value & chain value & ratio & TOA median\\" + "\n")
        for p in sorted(model.params):
            pm = getattr(model, p)
            for pfx in ["EQUAD", "ECORR", "EFAC", "DMEQUAD", "DMECORR", "TN"]: 
                if not p.startswith(pfx):
                    continue
                if pm.value is None:
                    break
                try:
                    pm_noise = getattr(fitter_noise.model, p)
                except AttributeError:
                    pm_noise_value = r"\cdot"
                    r = r"\cdot"
                else:
                    pm_noise_value = f"{pm_noise.value:.3g} {pm_noise.units}"
                    ratio = pm.value/pm_noise.value
                    r = f"{ratio:.2f}"
                    if not 0.9 < ratio < 1.1:
                        r = r"\textbf{" + r + "}"
                        any_bogus = True
                if hasattr(pm, "select_toa_mask"):
                    name = f"{p} {pm.key} {pm.key_value[0] if pm.key_value else pm.key_value}"
                else:
                    name = p
                if p.startswith("DMEQUAD"):
                    unc = np.median(fitter.toas.get_dm_errors().to_value(pint.dmu)[pm.select_toa_mask(fitter.toas)])
                    median = f"{unc:.3g} {pm.units}"
                elif p.startswith("EQUAD") or p.startswith("ECORR"):
                    unc = np.median(fitter.toas.table["error"][pm.select_toa_mask(fitter.toas)])
                    median = f"{unc:.3g} {pm.units}"
                else:
                    median = ""
                fsum.write(f"{verb(name)} & {pm.value:.3g} {pm.units} & {pm_noise_value} & {r} & {median}" + "\\\\\n")
        fsum.write(r"\end{tabular}\\" + "\n")
        if any_bogus:
            fsum.write("Some noise parameters (marked in bold) appear to be different "
                       "in the noise chains than in the par file.\\\\\n")
        model_set_params = {p for p in model.params if getattr(model, p).value is not None}
        noise_model_set_params = {p for p in fitter_noise.model.params if getattr(fitter_noise.model, p).value is not None}
        par_not_noise = list(sorted(model_set_params - noise_model_set_params))
        if par_not_noise:
            fsum.write("WARNING: the par file contains (a) parameter(s) missing from the post-noise model:")
            fsum.write(", ".join(verb(p) for p in par_not_noise))
            fsum.write(r"\\" + "\n")
        noise_not_par = list(sorted(model_set_params - noise_model_set_params))
        if noise_not_par:
            fsum.write("WARNING: the post-noise model contains (a) parameter(s) missing from the par file:")
            fsum.write(", ".join(verb(p) for p in noise_not_par))
            fsum.write(r"\\" + "\n")
    
    # Get lines to write for F-tests
    if NB:
        hdrline = "%42s %7s %9s %5s %s" % ("", "RMS(us)", "Chi2", "NDOF", "Ftest")
    else:
        hdrline = "%42s %7s %9s %9s %5s %s" % ("", "RMS(us)", "DM RMS(pc cm^-3)", "Chi2", "NDOF", "Ftest")
    fsum.write(r'\subsection*{Parameter tests}' + '\n')
    if Ftest_dict is None:
        fsum.write("\n")
        fsum.write("F test results not available.\\\\\n")
    else:
        ftest_lines = get_Ftest_lines(Ftest_dict, fitter)
        # Write F-test results
        fsum.write("F-test results used PINT\n")
        fsum.write(r'\begin{verbatim}' + '\n')
        fsum.write(hdrline + '\n')
        for l in ftest_lines:
            fsum.write(l + '\n')
        fsum.write(r'\end{verbatim}' + '\n')

    # Write if there are bad DMX ranges

    # NOTE - CURRENTLY CANNOT DO THIS, NEED DMX CHECKER FIRST
    if False:
        fsum.write(r'\subsection*{Check for bad DMX ranges, less than 10\% bandwidth}' + '\n')
        """
        if not is_wideband:
            if len(baddmx)==0:
                fsum.write('No bad dmx ranges\\\\\n')
            else:
                fsum.write('Bad DMX ranges found, %d out of %d DMX ranges:\\\\\n' % (len(baddmx),ndmx))
                for l in baddmx:
                    fsum.write('{\\tt '+l+'}\\\\\n')
        else:
            fsum.write('No fractional bandwidth check for DMX ranges with wideband data!\\\\\n')
        """
        if not NB:
            fsum.write('No fractional bandwidth check for DMX ranges with wideband data!\\\\\n')

    # compare_models
    fsum.write(r'\subsection*{Comparison with previous model}' + '\n')
    if previous_parfile is None:
        fsum.write("\n")
        fsum.write("No previous par file specified.\\\\\n")
    else:
        fsum.write("\n")
        fsum.write(f'Current par file: {verb(parfile)}' + '\\\\\n')
        fsum.write(f'Previous par file: {verb(previous_parfile)}' + '\\\\\n')
        fsum.write("\n")
        model_copy = copy.deepcopy(model)
        previous_model = get_model(previous_parfile)
        model_copy.name = "Current"
        previous_model.name = "Previous"
        try:
            cm = model_copy.compare(previous_model,
                               verbosity='max',
                               nodmx=True,
                               threshold_sigma=3)
        except ValueError as e:
            fsum.write(f"WARNING: {verb('compare_models')} failed because of {verb(e)}\\\\\n")
        else:
            fsum.write(r"{\small" + "\n")
            fsum.write(r"\begin{verbatim}" + "\n")
            fsum.write("\n".join(cm))
            fsum.write(r"\end{verbatim}" + "\n")
            fsum.write(r"}" + "\n")
            fsum.write("\n")
        
    # Write out software versions used
    fsum.write(r'\subsection*{Software versions used in timing\_analysis:}' + '\n')
    fsum.write('PINT: %s\\\\\n' % verb(pint.__version__))
    fsum.write('astropy: %s\\\\\n' % verb(astropy.__version__))
    fsum.write('numpy: %s\\\\\n' % verb(np.__version__))
    fsum.write('python: %s\\\\\n' % verb(sys.version))
    try:
        import enterprise
        fsum.write('enterprise: %s\\\\\n' % (enterprise.__version__))
    except ImportError as error:
        log.warning(str(error)+ ", cannot print enterprise version.")
    if False:
        # We didn't run PTMCMCSampler, no guarantee this is the relevant version
        try:
            import PTMCMCSampler
            fsum.write('PTMCMCSampler: %s\\\\\n' % (PTMCMCSampler.__version__))
        except ImportError as error:
            log.warning(str(error)+ ", cannot print PTMCMCSampler version.")
    if False:
        # We didn't actually use PSRCHIVE, so it's misleading to report a version here
        # If it's available from the TOAs we could report that
        try:
            # FIXME: this is the psrchive version on the notebook server, but we never use this version
            # Is there any point reporting it?
            psrchive_v = check_output(["psrchive", "--version"]).decode("utf-8")
            fsum.write('PSRCHIVE: %s\\\\\n' % (psrchive_v))
        except (ImportError, FileNotFoundError) as error:
            log.warning(str(error)+ ", cannot print PSRCHIVE version.")
    
    # Write out the plots - Assuming we have already made the summary plot previous to this
    # FIXME: why not make the summary plots here?
    # TODO Fix the plots...
    if NB:
        plot_file_list = sorted(glob.glob("%s*summary_plot_*_nb.*" % (model.PSR.value)))
    else:
        plot_file_list = sorted(glob.glob("%s*summary_plot_*_wb.*" % (model.PSR.value)))
    if not plot_file_list:
        raise IOError("Unable to find any summary plots to include in summary PDF!")
    for plot_file in plot_file_list:
        fsum.write(r'\begin{figure}[p]' + '\n')
        #fsum.write(r'\begin{center}' + '\n')
        #fsum.write(r'\vspace*{-2.0em}' + '\n')
        fsum.write(r'\centerline{\includegraphics[]{' + plot_file + '}}\n')
        #fsum.write(r'\end{center}' + '\n')
        fsum.write(r'\end{figure}' + '\n')
    nb_wb = "nb" if NB else "wb"
    noise_plot = f"{model.PSR.value}_noise_corner_{nb_wb}.pdf"
    if os.path.exists(noise_plot):
        log.info(f"Including noise corner plot {noise_plot}")
        fsum.write(r'\begin{figure}[p]' + '\n')
        fsum.write(r'\centerline{\includegraphics[width=\textwidth]{' + noise_plot + '}}\n')
        fsum.write(r'\end{figure}' + '\n')
    else:
        log.info(f"Could not find noise corner plot {noise_plot}")
        fsum.write(f"Noise corner plot {verb(noise_plot)} not found.\\\\\n")
        

    if append is None:

        fsum.write(r'\end{document}' + '\n')
        fsum.close()

        try:
            check_call(['pdflatex','-interaction=batchmode', texfile])
        except CalledProcessError as e:
            log.warning(f"Latex run failed: {e}")

def write_if_changed(filename, contents):
    """Write contents to filename, touching the file only if it does not already contain them.
    
    Inputs:
    ----------
    filename [string]: Name of a text file.
    contents [string]: Sting to write to the file.
    """
    if os.path.exists(filename):
        if contents == open(filename).read():
            return
    with open(filename, "w") as f:
        f.write(contents)

def apply_cut_flag(toas, selection, flagvalue, warn=False):
    """Apply appropriate cut flag to a selection of toas.

    Inputs:
    ----------
    toas [pint.TOA]: PINT TOA object
    selection [bool]: Boolean array, True designates TOAs to cut
    flagvalue [string]: String to apply to TOA line
    """
    names = toas.get_flag_value('name')[0]
    chans = toas.get_flag_value('chan')[0]
    subints = toas.get_flag_value('subint')[0]
    cuts = toas.get_flag_value('cut')[0]
    for i,s in enumerate(selection):
        if s and (not cuts[i]):
            toas.table['flags'][i]['cut'] = flagvalue
        elif cuts[i] is not None and warn:
            log.warning(f'Skipping TOA {names[i]} (chan {chans[i]}, subint {subints[i]}) already cut: {cuts[i]}.')

def apply_cut_select(toas,reason='???'):
    """Apply toa selection based on cut flags present.

    Inputs:
    ----------
    toas [pint.TOA]: PINT TOA object
    reason [string]: String 
    """
    cutselect = np.array([(not c) for c in toas.get_flag_value('cut')[0]])
    if 'ignore' in reason:
        fout = 'ignore_cut.tim'
    elif 'ratio' in reason:
        fout = 'dmx_cut.tim'
    else:
        fout = 'other_cut.tim'

    if sum(cutselect) != toas.ntoas:
        cut = np.logical_not(cutselect)
        cut_toas = toas[cut]
        cut_toas.write_TOA_file(fout, format='tempo2')

        log.info(f"Selecting {sum(cutselect)} TOAs out of {toas.ntoas} ({sum(cut)} removed based on {reason}).")
        toas.select(cutselect)
    else:
        pass
