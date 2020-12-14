# Timing analysis

A long-lived repository for NANOGrav Timing analysis work.

Installing on the notebook server
---------------------------------

1. Go to notebook.nanograv.org and sign in with your NANOGrav.org Google Account. Your username should follow the convention of FirstName.LastName@nanograv.org. If you have any issues, please submit a ticket at http://support.nanograv.org and a CyberI team member will address it quickly.

2. Once logged in, you can access the terminal by navigating to the 'New' drop-down and selecting 'Terminal'. (Note: you will be user "jovyan" but in your own separate userspace/container)

3. Clone timing_analysis to your (i.e. "jovyan") home directory and checkout the working branch; in a terminal:
```
> cd ~/work/
> git clone git@gitlab.nanograv.org:nano-time/timing_analysis.git
> cd timing_analysis
> git checkout -b 15yr origin/15yr
```
If the last command tells you `15yr` exists already, great.

In order to ensure commits are pushed as your NANOGrav.org GitLab account rather than the "jovyan" user, please run the following commands to configure the `timing_analysis` directory.
```
cd ~/work/timing_analysis/
git config user.name "FirstName LastName"
git config user.email "FirstName.LastName@nanograv.org"
```
Note: You may have to reconfigure this if your container is brought down at any point. This should be remedied in the future.

4. Get the latest copy of PINT; in a terminal:
```
> pip install git+git://github.com/nanograv/pint --user
```

5. To install and make sure paths are set up properly, `cd` into `timing_analysis` and:
```
pip install .
```

Timing workflow
---------------

This package has a variety of tools to support timing for NANOGrav, but the basic goal here is to produce a config `.yaml` file and a `.par` file that together produce clean timing residuals for a new pulsar. (If the pulsar is new to long-term timing, you may need more tools than this to put together an initial `.par` file.) This section will describe how to do that.

1. Pick a pulsar for which timing hasn't been finalized, but for which `.tim` and initial `.par` files exist. The easiest may just be to look in `results` and the most recetn `/nanograv/timing/releases/15y/toagen/releases/` for pulsars not represented in `config`. You might also check https://gitlab.nanograv.org/nano-time/timing_analysis/-/branches to make sure no one is working on it.

2. Make a branch for your work on the new pulsar, say J1234+5678:
```
$ git checkout 15yr
$ git checkout -b psr/J1234+5678/{your_initials}
```

3. Copy `config/template.yaml` to `config/J1234+5678.yaml` and fill in the basic parameters, in particular `.par` file (will probably be in `results/`) and `.tim` file(s) (will probably be in the most recent release under `/nanograv/releases/15y/toagen/releases/`). For now you may want to select *narrowband* `.tim` files (indicated by `.nb.tim` rather than `.wb.tim`) and set the corresponding option in the `.yaml` file; the machinery to do this for wideband TOAs is not as well developed. 

4. You may need to select which parameters to fit - at a minimum they should be ones that are in the `.par` file. For position, prefer `ELONG`/`ELAT` rather than `RAJ`/`DECJ` or `LAMBDA`/`BETA`; likewise the proper motion parameters `PMELONG`/`PMELAT`. More, NANOGrav policy is that all pulsars should be fit for at least `ELONG`, `ELAT`, `PMELONG`, `PMELAT`, `PX`, `F0`, `F1` in every pulsar.

5. Copy the template notebook to the root directory (where you should probably work):
```
$ cp nb_templates/newmsp_notebook_v2.0.ipynb J1234+5678.ipynb
```

6. Open the notebook, fill in your pulsar name, and try running it. Various things will go wrong.

7. Fix all the things. (See below.)

Timing the pulsar
-----------------

There are a lot of things that can go wrong at this point; that's why this isn't an automated process, and why you have a notebook. Here are a few things that might come up, and some suggestions:

- Can't find your `.par` file: you probably need to use `results/J1234+5678.12.5yr.par`, that is, include the directory.

- Can't find one or all of your `.tim` files: make sure you can see them at that location on the same machine your notebook is running on. You probably need to be on the NANOGrav notebook server.

- Few TOAs and they look weird: Wideband TOAs may not work well, and nothing will work if the `toa-type` doesn't match the kind of TOA you're using.

- Tons of PINT `INFO` messages: sadly, this is normal.

- Plots are thrown off by a few points with huge error bars: You should be able to zoom in and identify the MJD, then open the `.tim` file and find which TOAs from this day have huge uncertainties. You can use the excision features in the `.yaml` file to remove these.

- Plots are thrown off by lots of points with huge error bars: consider adjusting `snr-cut` to remove the ones with the worst signal-to-noise.

- Plots are thrown off by a few outliers with normal error bars: For a proper analysis we should definitely understand what's wrong with these. For now it may be okay to just excise them. It's not as easy as one might wish to figure out which ones they are yet, but there is the function `large_residuals()` which will print out some of the largest in a format suitable for excision.

- Post-fit model is bad: You may need to fit for more parameters, or switch timing models. 

- `ELL1` approximation bad warning message: You probably want to switch to `DD`; they have suggested parameters there, so just create a temporary `.par` file and edit it, putting those values in. This may require some fitting. 

- The fit is so bad you have a phase wrap: You may be able to resolve this by temporarily using the `.yaml` to restrict to a shorter time interval, or using PINT commands to do so, fit, write out a `.par` file with `write_par` and use it for the input, then move to a longer time interval. Repeat as necessary.

- Your `.par` file looks terrible but is fine in TEMPO2: it's probably in the TCB timescale, which PINT does not support. Use `tempo2 -gr transform old.par new.par tdb` to convert it.

- You see weird kinks in the time series, or peaks at orbital phase 0.25, or sinusoidal variations with orbital phase that change over time: you may need to add features to your timing model.

There are a number of helpful functions available in `timing_analysis.lite_utils` that are imported at the top of the template notebook; you may want to look inside the `src/timing_analysis/lite_utils.py`, which contains the functions and some documentation. You might also try `import timing_analysis.lite_utils; dir(lite_utils)`.

Submitting a good timing solution
---------------------------------

When you have a post-fit timing solution that seems good - no wild outliers, no visible structure in terms of time or orbital phase, reduced chi-squared not too far above 1, no warnings from the timing model - you are probably ready to commit the new timing model to the `timing_analysis` repository.

1. Generate an output `.par` file; this can be done by having the notebook run `write_par(fo)` on a successful fitter `fo`. This will create a file `J1234+5678_PINT_YYYYMMDD.par` in your working directory.

2. Archive the old `.par` file and put the new one in place:
```
$ git mv results/J1234+5678.12.5yr.par results/archive/
$ cp J1234+5678_PINT_YYYYMMDD.par results/
$ git add results/J1234+5678_PINT_YYYYMMDD.par
```

3. Update `config/J1234+5678.par` to use this new par file; place the old one as `compare-model`. Rerun the notebook and confirm that all is well and that both pre-fit and post-fit are good fits, and indistinguishable.

4. Go through the checklist at https://gitlab.nanograv.org/nano-time/timing_analysis/-/wikis/Review-Checklists-For-Merging

5. Submit it to the gitlab:
```
$ git commit
$ git push
```
An error message appears with the command you should have run instead; run that. (It'll be something involving `--set-upstream origin` but it's easier to just let git suggest it.)

6. Create a merge request for your branch - this asks one of the maintainers to look at your work and if it's okay make it part of the official repository. I recommend including at least the reduced chi-squared and a post-fit residuals plot, or you could just attach a PDF of the timing notebook. 

7. Respond to any comments or questions or requests for adjustment the maintainers raise; when they are happy they will merge it.

Congratulations, you have timed a pulsar for NANOGrav!

Other development
-----------------

Current development is being done on the 15yr branch, so please make sure to point merge requests there. Checkout development branches using the naming convention for pulsars/features as follows:
```
> git checkout -b psr/J1234+5678/[initials]
> git checkout -b feature/[brief_description]
```
