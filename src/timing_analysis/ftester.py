""" This is a set of utilities which performs F-test calculations for parameter inclusion/exclusion """


'''
fitter.ftest('list of PINT parameter objects', 'list of corresponding timing model components', remove=True/False, full_output = True) and this will output a dictionary with keys: ft, resid_rms_test, resid_wrms_test, chi2_test, dof_test, where the test values are of the nested modeled that was tested.

'''



import warnings
#from pint.models import (
#    parameter as p,
#)
import timing_analysis.PINT_parameters as pparams
import pint.models as model
import copy
import astropy.units as u

ALPHA = 0.0027

# Function to check if the parameter is in the model
def param_check(name, fitter, check_enabled=True):
    if not name in fitter.model.params:
        return False
    # If frozen is False, then it's fit for, if frozen is True, parameter not fit for
    if check_enabled and getattr(fitter.model, "{:}".format(name)).frozen:
        return False
    return True

# Function to get list of fb parameters
def get_fblist(fitter):
    """
    Returns the list of FB parameters for the ELL1 model.

    Input:
    --------
    fitter: The PINT fitter object, which contains the TOAs and the models

    Returns:
    --------
    fblist : dictionary
        dictionary of FB parameters
    """
    fblist = {}
    for p in fitter.model.params:
        if p.startswith("FB") and not p.startswith("FBJ") and getattr(fitter.model, p).value != None:
            if len(p)==2:
                fblist[0] = p
            else:
                fblist[int(p[2:])] = p
    fbbad = False
    k = sorted(fblist.keys())
    for i, ifb in zip(range(len(fblist)),sorted(fblist.keys())):
        if i!=ifb:
            fbbad = True
    if fbbad:
        print_bad("FB parameters not a series of integers: "+
             " ".join([fblist[i] for i in k]) )
    return fblist

# Function to get binary parameters for F-tests
def binary_params_ftest(bparams, fitter, remove):
    """
    Returns the list of parameters and components to put in the check for binary models.

    Input:
    --------
    bparams : list
        List of binary parameters to check for.
    fitter: The PINT fitter object, which contains the TOAs and the models
    remove : boolean
        If True, check to see if parameters need to be removed, if False check to see
        what parameters need to be added.

    Returns:
    --------
    plist : list
        List of PINT parameters to iterate through for the F-tests.
    clist : list
        List of the PINT components to iterate through for the F-tests.
    """
    # list of parameters as strings to remove or add in the F-test
    p_test = []
    # list of PINT parameters to test
    pint_params = []
    # And their associated timing model components
    pint_comps = []
    # get binary model to add to component
    b_ext = fitter.model.binary_model_name
    # If we want to test removing parameters from the binary model
    if remove:
        # Figure out what is in the model and needs to be removed
        for bp in bparams:
            if param_check(bp, fitter):
                p_test.append(bp)
    else:
        # Figure out what is in the model and needs to be removed
        for bp in bparams:
            if not param_check(bp, fitter):
                p_test.append(bp)
    # Check M2 SINI specifically
    if 'M2' in p_test and 'SINI' in p_test:
        pint_params.append([pparams.M2, pparams.SINI])
        pint_comps.append([pparams.M2_Component+b_ext, pparams.SINI_Component+b_ext])
    # Get the rest of the parameters and components
    for pr in p_test:
        if pr == 'M2' or pr == 'SINI' or pr == 'EPS1DOT' or pr == 'EPS2DOT':
            pass
        else:
            # Check for H3/H4 -> This may not be quite right, may need to change later
            if pr == 'H4' and 'H3' in p_test:
                pass
            else:
                pint_params.append([getattr(pparams, pr)])
                pint_comps.append([getattr(pparams, pr+'_Component')+b_ext])
    # Check EPS1/2DOT specifically
    if 'EPS1DOT' in p_test and 'EPS2DOT' in p_test:
        pint_params.append([pparams.EPS1DOT, pparams.EPS2DOT])
        pint_comps.append([pparams.EPS1DOT_Component+b_ext, pparams.EPS2DOT_Component+b_ext])
    # Check H3 and H4 specifically
    if 'H3' in p_test and 'H4' in p_test:
        pint_params.append([pparams.H3, pparams.H4])
        pint_comps.append([pparams.H3_Component+b_ext, pparams.H4_Component+b_ext])
    # return the values
    return pint_params, pint_comps

# from finalize timing, pretty printing function/lines
def report_ptest(label, rms, chi2, ndof, Fstatistic=None, alpha=ALPHA):
    if Fstatistic is None:
        line = "%42s %7.3f %9.2f %5d --" % (label, rms, chi2, ndof)
    elif Fstatistic:
        line = "%42s %7.3f %9.2f %5d %.3g" % (label, rms, chi2, ndof, Fstatistic)
        if Fstatistic < alpha:
            line += " ***"
    else:
        line = "%42s %7.3f %9.2f %5d xxx" % (label, rms, chi2, ndof)
    print(line)

# Function to reset parameters to 0 +/- 0
def reset_params(params):
    """
    This will reset the parameters imported from PINT_parameters to values of zero after they
    have been fit for. (Not sure why this happens but needs to be here...)
    """
    for p in params:
        if p.name == 'M2':
            p.value = 0.25
            p.uncertainty = 0.0
        elif p.name == 'SINI':
            p.value = 0.8
            p.uncertainty = 0.0
        else:
            p.value = 0.0
            p.uncertainty = 0.0

def run_Ftests(fitter, alpha=ALPHA):
    """
    This is the main function to run the various F-tests below.
    Will print ...?
    Will return... ?

    Parameters
    ==========
    fitter: The PINT fitter object, which contains
        the TOAs and the models
    alpha (optional): the F-test significance value
    """
    # Check if fitter is wideband or not
    if "Wideband" in fitter.__class__.__name__:
        NB = False
        resids = fitter.resids.residual_objs[0]
        dm_resids = fitter.resids.residual_objs[1]
    else:
        NB = True
        resids = fitter.resids

    # Define return dictionary, format tbd
    retdict = {}
    # Start with initial printing from Finalize Timing:
    print("Testing additional parameters (*** = significant):")
    hdrline = "%42s %7s %9s %5s %s" % ("", "RMS(us)", "Chi2", "NDOF", "Ftest")
    print(hdrline)
    base_rms = resids.time_resids.std().to(u.us)
    base_wrms = resids.rms_weighted() # assumes the input fitter has been fit already
    base_chi2 = resids.calc_chi2()
    base_ndof = resids.get_dof()
    if NB:
        # Add initial values to F-test dictionary
        retdict['initial'] = {'ft':None, 'resid_rms_test':base_rms, 'resid_wrms_test':base_wrms, 'chi2_test':base_chi2, 'dof_test':base_ndof}
    else:
        base_chi2 = resids.calc_chi2() + dm_resids.calc_chi2()
        time_chi2_test = resids.calc_chi2()
        dm_chi2_test = dm_resids.calc_chi2()
        dm_resid_rms_test = dm_resids.resids.std()
        dm_resid_wrms_test = dm_resids.rms_weighted()
        # Add initial values to F-test dictionary
        retdict['initial'] = {'ft':None, 'resid_rms_test':base_rms, 'resid_wrms_test':base_wrms, 'chi2_test':base_chi2, 'dof_test':base_ndof, "dm_resid_rms_test": dm_resid_rms_test, "dm_resid_wrms_test": dm_resid_wrms_test, "dm_chi2_test": dm_chi2_test, "time_chi2_test": time_chi2_test}
    # Now report the values
    report_ptest("initial", base_wrms.value, base_chi2, base_ndof)

    # Check adding binary parameters
    print("Testing additional parameters:")
    retdict['Add'] = {}
    if hasattr(fitter.model, "binary_model_name"):
        if fitter.model.binary_model_name == 'DD':
            binarydict = check_binary_DD(fitter, alpha=ALPHA, remove = False)
        elif fitter.model.binary_model_name == 'DDK':
            binarydict = check_binary_DDK(fitter, alpha=ALPHA, remove = False)
        elif fitter.model.binary_model_name == 'ELL1':
            binarydict = check_binary_ELL1(fitter, alpha=ALPHA, remove = False)
        elif fitter.model.binary_model_name == 'ELL1H':
            binarydict = check_binary_ELL1H(fitter, alpha=ALPHA, remove = False)
        retdict['Add']['Binary'] = binarydict
    print("Testing removal of parameters:")
    retdict['Remove'] = {}
    # Check parallax, NOTE - cannot remove PX if binary model is DDK, so check for that.
    if hasattr(fitter.model, "binary_model_name"):
        if fitter.model.binary_model_name == 'DDK':
            print(" PX, KOM and KIN cannot be removed in DDK.")
        else:
            PXdict = check_PX(fitter, alpha=ALPHA)
            retdict['Remove']['PX'] = PXdict['PX']
    else:
        PXdict = check_PX(fitter, alpha=ALPHA)
        retdict['Remove']['PX'] = PXdict['PX']
    # Check removing binary parameters
    if hasattr(fitter.model, "binary_model_name"):
        if fitter.model.binary_model_name == 'DD':
            binarydict = check_binary_DD(fitter, alpha=ALPHA, remove = True)
        elif fitter.model.binary_model_name == 'DDK':
            binarydict = check_binary_DDK(fitter, alpha=ALPHA, remove = True)
        elif fitter.model.binary_model_name == 'ELL1':
            binarydict = check_binary_ELL1(fitter, alpha=ALPHA, remove = True)
        elif fitter.model.binary_model_name == 'ELL1H':
            binarydict = check_binary_ELL1H(fitter, alpha=ALPHA, remove = True)
        retdict['Remove']['Binary'] = binarydict
    # Get current number of spin frequency derivatives
    current_freq_deriv = 1
    for i in range(2,21):
        p = "F%d" % i
        if p in fitter.model.params:
            current_freq_deriv = i
    print("Testing spin freq derivs (%s enabled):" % (current_freq_deriv))
    # NOTE - CURRENTLY ONLY TESTS F2
    F2dict = check_F2(fitter, alpha=ALPHA)
    retdict['F'] = F2dict
    # Now check FB parameters
    if hasattr(fitter.model, "binary_model_name"):
        if fitter.model.binary_model_name == 'ELL1':
            FBdict = check_FB(fitter, alpha=ALPHA, fbmax = 5)
            if FBdict:
                retdict['FB'] = FBdict
    # Now run various functions individually (FD only right now):
    FDdict = check_FD(fitter, alpha=ALPHA, maxcomponent=5)
    retdict['FD'] = FDdict

    return retdict


def check_F2(fitter, alpha=ALPHA):
    """
    Check the significance of F2
    In general, we do not allow F2 to be added but
    we will still check as in the past

    Parameters
    ==========
    fitter: The PINT fitter object, which contains
        the TOAs and the models
    alpha (optional): the F-test significance value

    Returns
    =======
    Returns the dictionary output from the F-tests
    """
    # Add dictionary for return values
    retdict = {}
    # Run the F2 F-test
    ftest_dict = fitter.ftest(pparams.F2, pparams.F2_Component, remove=False, full_output=True)
    # Add to dictionary
    retdict['F2'] = ftest_dict
    report_ptest('F2', ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
    # This edits the values in the file for some reason, want to reset them to zeros
    reset_params([pparams.F2])
    # Return the dictionary
    return retdict


def check_PX(fitter, alpha=ALPHA):
    """
    Check the significance of PX
    In general, we fit PX but we still wish to
    test for this as in the past

    Parameters
    ==========
    fitter: The PINT fitter object, which contains
        the TOAs and the models
    alpha (optional): the F-test significance value

    Returns
    =======
    Returns the dictionary output from the F-tests
    """
    # Add dictionary for return values
    retdict = {}
    # Run the parallax F-test
    ftest_dict = fitter.ftest(pparams.PX, pparams.PX_Component, remove=True, full_output=True)
    # Add to dictionary
    retdict['PX'] = ftest_dict
    # Print results
    report_ptest('PX', ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
    # This edits the values in the file for some reason, want to reset them to zeros
    reset_params([pparams.PX])
    # Return the dictionary
    return retdict

    #if ftest_dict['ft'] < alpha:
    #    return True
    #return False

def check_FD(fitter, alpha=ALPHA, maxcomponent=5):
    """
    Unlike previously, these are being used as a check.
    As such, we only need to worry about adding components
    and not removing them.

    Note: this uses eval()

    BJS: Could/Should we use `getattr(p, 'FD%s'%(i))` instead?
    """
    # Print how many FD currently enabled
    cur_fd = [param for param in fitter.model.params if "FD" in param]
    print("Testing FD terms (", cur_fd, "enabled):")
    # Add dictionary for return values
    retdict = {}
    # For FD, need to remove components and then add it back in to start with no FD parameters
    psr_fitter_nofd = copy.deepcopy(fitter)
    try:
        psr_fitter_nofd.model.remove_component('FD')
    except:
        warnings.warn("No FD parameters in the initial timing model...")

    # Check if fitter is wideband or not
    if "Wideband" in fitter.__class__.__name__:
        NB = False
        resids = fitter.resids.residual_objs[0]
        dm_resids = fitter.resids.residual_objs[1]
    else:
        NB = True
        resids = fitter.resids

    psr_fitter_nofd.fit_toas(1) # May want more than 2 iterations
    base_rms_nofd = resids.time_resids.std().to(u.us)
    base_wrms_nofd = resids.rms_weighted()
    base_ndof_nofd = resids.get_dof()
    base_chi2_nofd = resids.calc_chi2()
    # Add to dictionary
    if NB:
        retdict['NoFD'] = {'ft':None, 'resid_rms_test':base_rms_nofd, 'resid_wrms_test':base_wrms_nofd, 'chi2_test':base_chi2_nofd, 'dof_test':base_ndof_nofd}
    else:
        base_chi2_nofd = resids.calc_chi2() + dm_resids.calc_chi2()
        time_chi2_test = resids.calc_chi2()
        dm_chi2_test = dm_resids.calc_chi2()
        dm_resid_rms_test = dm_resids.resids.std()
        dm_resid_wrms_test = dm_resids.rms_weighted()
        # Add initial values to F-test dictionary
        retdict['initial'] = {'ft':None, 'resid_rms_test':base_rms_nofd, 'resid_wrms_test':base_wrms_nofd, 'chi2_test':base_chi2_nofd, 'dof_test':base_ndof_nofd, "dm_resid_rms_test": dm_resid_rms_test, "dm_resid_wrms_test": dm_resid_wrms_test, "dm_chi2_test": dm_chi2_test, "time_chi2_test": time_chi2_test}
    # and report the value
    report_ptest("no FD", base_wrms_nofd.value, base_chi2_nofd, base_ndof_nofd)
    # Now re-add the FD component to the timing model
    all_components = model.timing_model.Component.component_types
    fd_class = all_components["FD"]
    fd = fd_class()
    psr_fitter_nofd.model.add_component(fd, validate=False)

    param_list = []
    component_list = []
    for i in range(1, maxcomponent+1):
        param_list.append(getattr(pparams, 'FD%s'%(i)))
        component_list.append(getattr(pparams, "FD%i_Component"%(i)))
        # Run F-test
        ftest_dict = psr_fitter_nofd.ftest(param_list, component_list, remove=False, full_output=True)
        # Add to dictionary to return
        retdict['FD%s'%i] = ftest_dict
        # Print results
        report_ptest('FD1 through FD%s'%i, ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
        # This edits the values in the file for some reason, want to reset them to zeros
        reset_params(param_list)
    # Return the dictionary
    return retdict


def check_binary_DD(fitter, alpha=ALPHA, remove = False):
    """
    Check the binary parameter F-tests for the DD binary model, either removing or adding parameters.

    Parameters
    ==========
    fitter: The PINT fitter object, which contains
        the TOAs and the models
    alpha (optional): the F-test significance value
    remove : Boolean, True or False. If True, will do and report F-test values for removing parameters.
             If False, will look for and report F-test values for adding parameters.
             Parameters to check:
                1. M2, SINI
                2. PBDOT
                3. XDOT -> A1DOT
                4. OMDOT
                5. EDOT

    Returns
    =======
    Returns the dictionary output from the F-tests
    """
    # Add dictionary for return values
    retdict = {}
    # Params to check
    DDparams = ['M2', 'SINI', 'PBDOT', 'A1DOT', 'OMDOT' ,'EDOT']
    # Get the components and run the F-test
    # get list of parameters for F-tests
    pint_params, pint_comps = binary_params_ftest(DDparams, fitter, remove)
    # Now get the list of components and parameters to run the F-test; Check M2 SINI specifically
    for ii in range(len(pint_params)):
        ftest_dict = fitter.ftest(pint_params[ii], pint_comps[ii], remove=remove, full_output=True)
        # Get dictionary label
        if len(pint_params[ii]) > 1:
            d_label = "M2, SINI"
        else:
            d_label = pint_params[ii][0].name
        # Add the dictionary
        retdict[d_label] = ftest_dict
        # Print the results
        report_ptest(d_label, ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
        # Reset the parameters
        reset_params(pint_params[ii])
    # Return the dictionary
    return retdict

def check_binary_DDK(fitter, alpha=ALPHA, remove = False):
    """
    Check the binary parameter F-tests for the DDK binary model, either removing or adding parameters.

    Parameters
    ==========
    fitter: The PINT fitter object, which contains
        the TOAs and the models
    alpha (optional): the F-test significance value
    remove : Boolean, True or False. If True, will do and report F-test values for removing parameters.
             If False, will look for and report F-test values for adding parameters.
             Parameters to check:
                1. M2, SINI
                2. PBDOT
                3. XDOT -> A1DOT
                4. OMDOT
                5. EDOT

    Returns
    =======
    Returns the dictionary output from the F-tests
    """
    # Add dictionary for return values
    retdict = {}
    # Params to check
    DDKparams = ['M2', 'SINI', 'PBDOT', 'A1DOT', 'OMDOT' ,'EDOT']
    # Get the components and run the F-test
    # get list of parameters for F-tests
    pint_params, pint_comps = binary_params_ftest(DDKparams, fitter, remove)
    # Now get the list of components and parameters to run the F-test; Check M2 SINI specifically
    for ii in range(len(pint_params)):
        ftest_dict = fitter.ftest(pint_params[ii], pint_comps[ii], remove=remove, full_output=True)
        # Get dictionary label
        if len(pint_params[ii]) > 1:
            d_label = "M2, SINI"
        else:
            d_label = pint_params[ii][0].name
        # Add the dictionary
        retdict[d_label] = ftest_dict
        # Print the results
        report_ptest(d_label, ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
        # Reset the parameters
        reset_params(pint_params[ii])
    # Return the dictionary
    return retdict


def check_binary_ELL1(fitter, alpha=ALPHA, remove = False):
    """
    Check the binary parameter F-tests for the ELL1 binary model, either removing or adding parameters.

    Parameters
    ==========
    fitter: The PINT fitter object, which contains
        the TOAs and the models
    alpha (optional): the F-test significance value
    remove : Boolean, True or False. If True, will do and report F-test values for removing parameters.
             If False, will look for and report F-test values for adding parameters.
             Parameters to check:
                1. PB
                    a. M2, SINI
                    b. PBDOT
                    c. XDOT -> A1DOT
                    d. EPS1DOT, EPS2DOT
                2. FB0, FB1
                    a. FB2-FB6+ ( These are checked by running `check_FB()` )
                    b. XDOT -> A1DOT
                    c. EPS1DOT, EPS2DOT
    fbmax : int
        Number of FB parameters to check in the F-tests, default is 5

    Returns
    =======
    Returns the dictionary output from the F-tests
    """
    # Define dictionary for returned value
    retdict = {}
    # Check if FB is used (Use the same function as in previous finalize time, but PINT-ified
    fblist = get_fblist(fitter)
    fbused = (len(fblist)>0)
    # Get the parameters that are used (not including FB values)
    if not fbused:
        ELL1params = ['M2', 'SINI', 'PBDOT', 'A1DOT', 'EPS1DOT' ,'EPS2DOT']
    else:
        ELL1params = ['A1DOT', 'EPS1DOT' ,'EPS2DOT']
    # Check not using FB first
    if not fbused:
        # get list of parameters for F-tests
        pint_params, pint_comps = binary_params_ftest(ELL1params, fitter, remove)
        # Now get the list of components and parameters to run the F-test; Check M2 SINI specifically
        for ii in range(len(pint_params)):
            ftest_dict = fitter.ftest(pint_params[ii], pint_comps[ii], remove=remove, full_output=True)
            # Get dictionary label
            if len(pint_params[ii]) > 1 and (pint_params[ii][0].name == 'M2' or pint_params[ii][0].name == 'SINI'):
                d_label = "M2, SINI"
            elif len(pint_params[ii])>1 and (pint_params[ii][0].name == 'EPS1DOT' or pint_params[ii][0].name == 'EPS2DOT'):
                d_label = "EPS1DOT, EPS2DOT"
            else:
                d_label = pint_params[ii][0].name
            # Add the dictionary
            retdict[d_label] = ftest_dict
            # Print the results
            report_ptest(d_label, ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
            # Reset the parameters
            reset_params(pint_params[ii])
        # Return the dictionary
        return retdict
    # If we use FB parameters, check that, this will be more like the FD parameters
    else:
        # Now check other parameters, not FB
        pint_params, pint_comps = binary_params_ftest(ELL1params, fitter, remove)
        # Now get the list of components and parameters to run the F-test; Check M2 SINI specifically
        for ii in range(len(pint_params)):
            ftest_dict = fitter.ftest(pint_params[ii], pint_comps[ii], remove=remove, full_output=True)
            # Get dictionary label
            if len(pint_params[ii]) > 1 and (pint_params[ii][0].name == 'M2' or pint_params[ii][0].name == 'SINI'):
                d_label = "M2, SINI"
            elif len(pint_params[ii])>1 and (pint_params[ii][0].name == 'EPS1DOT' or pint_params[ii][0].name == 'EPS2DOT'):
                d_label = "EPS1DOT, EPS2DOT"
            else:
                d_label = pint_params[ii][0].name
            # Add the dictionary
            retdict[d_label] = ftest_dict
            # Print the results
            report_ptest(d_label, ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
            # Reset the parameters
            reset_params(pint_params[ii])
        # Return the dictionary
        return retdict

def check_binary_ELL1H(fitter, alpha=ALPHA, remove = False):
    """
    Check the binary parameter F-tests for the ELL1H binary model, either removing or adding parameters.

    Parameters
    ==========
    fitter: The PINT fitter object, which contains
        the TOAs and the models
    alpha (optional): the F-test significance value
    remove : Boolean, True or False. If True, will do and report F-test values for removing parameters.
             If False, will look for and report F-test values for adding parameters.
             Parameters to check:
                1. PBDOT
                2. XDOT -> A1DOT
                3. EPS1DOT, EPS2DOT
                4. H3
                    a. H4

    Returns
    =======
    Returns the dictionary output from the F-tests
    """
    # Define dictionary for returned value
    retdict = {}
    # Get the parameters that are used
    ELL1Hparams = ['PBDOT', 'A1DOT', 'EPS1DOT' ,'EPS2DOT', 'H3', 'H4']
    # get list of parameters for F-tests
    pint_params, pint_comps = binary_params_ftest(ELL1Hparams, fitter, remove)
    # Now get the list of components and parameters to run the F-test; Check M2 SINI specifically
    for ii in range(len(pint_params)):
        ftest_dict = fitter.ftest(pint_params[ii], pint_comps[ii], remove=remove, full_output=True)
        # Get dictionary label
        if len(pint_params[ii]) > 1 and (pint_params[ii][0].name == 'H3' or pint_params[ii][0].name == 'H4'):
            d_label = "H3, H4"
        elif len(pint_params[ii])>1 and (pint_params[ii][0].name == 'EPS1DOT' or pint_params[ii][0].name == 'EPS2DOT'):
            d_label = "EPS1DOT, EPS2DOT"
        else:
            d_label = pint_params[ii][0].name
        # Add the dictionary
        retdict[d_label] = ftest_dict
        # Print the results
        report_ptest(d_label, ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
        # Reset the parameters
        reset_params(pint_params[ii])
    # Return the dictionary
    return retdict

def check_FB(fitter, alpha=ALPHA, fbmax = 5):
    """
    Check the FB parameter F-tests for the ELL1 binary model doing both removing and addtion.

    Parameters
    ==========
    fitter: The PINT fitter object, which contains
        the TOAs and the models
    alpha (optional): the F-test significance value
    fbmax : int
        Number of FB parameters to check in the F-tests, default is 5

    Returns
    =======
    Returns the dictionary output from the F-tests
    """
    # Define dictionary for returned value
    retdict = {}
    # Check if FB is used (Use the same function as in previous finalize time, but PINT-ified
    fblist = get_fblist(fitter)
    fbused = (len(fblist)>0)
    if fbused:
        # First check FB parameters - print the corrent number of FB parameters used
        fbp = [fblist[ifb] for ifb in sorted(fblist.keys())]  # sorted list of fb parameters
        print("Testing FB parameters, present list: "+" ".join(fbp))
        # Now run the F-tests, first try removing FB parmaters
        print("Testing removal of FB parameters:")
        for i in range(1,len(fblist)):
            p = [fbp[j] for j in range(i,len(fbp))]
            param_list = [(getattr(pparams, fp)) for fp in p]
            component_list = [(getattr(pparams, "%s_Component"%(fp))+"ELL1") for fp in p]
            # Run F-test
            ftest_dict = fitter.ftest(param_list, component_list, remove=True, full_output=True)
            # Add to dictionary to return
            retdict['FB%s+'%i] = ftest_dict
            # Print results
            report_ptest(" ".join(p), ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
            # This edits the values in the file for some reason, want to reset them to zeros
            reset_params(param_list)
    # Now try adding FB parameters
        print("Testing addition of FB parameters:")
        for i in range(len(fblist),fbmax+1):
            p = ["FB%d" % (j) for j in range(len(fblist),i+1)]
            param_list = [(getattr(pparams, fp)) for fp in p]
            component_list = [(getattr(pparams, "%s_Component"%(fp))+"ELL1") for fp in p]
            # Run F-test
            ftest_dict = fitter.ftest(param_list, component_list, remove=False, full_output=True)
            # Add to dictionary to return
            retdict['FB%s'%i] = ftest_dict
            # Print results
            report_ptest(" ".join(p), ftest_dict['resid_wrms_test'].value, ftest_dict['chi2_test'], ftest_dict['dof_test'], Fstatistic=ftest_dict['ft'], alpha=ALPHA)
            # This edits the values in the file for some reason, want to reset them to zeros
            reset_params(param_list)
        # Now return the dictionary
        return retdict
    else:
        warnings.warn("No FB parameters in the initial timing model...")
        return False

    