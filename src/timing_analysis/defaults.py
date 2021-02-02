# Here we keep track of global default settings

# Choice of clock, SSE
LATEST_BIPM = "BIPM2019"    # latest clock realization to use
LATEST_EPHEM = "DE438"      # latest solar system ephemeris to use

# Toggle various corrections
PLANET_SHAPIRO = True       # correct for Shapiro delay from planets
CORRECT_TROPOSPHERE = True  # cprrect for tropospheric delays

# DMX model defaults
FREQUENCY_RATIO = 1.1       # set the high/low frequency ratio for DMX bins
MAX_SOLARWIND_DELAY = 0.1   # set the maximum permited 'delay' from SW [us]
