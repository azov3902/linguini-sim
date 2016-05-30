############################################################################################
#
# 	File:		apd_etc.py
#	Author:		Anna Zovaro
#	Email:		anna.zovaro@anu.edu.au
#	Edited:		25/05/2016
#
#	Description:
#	An exposure time calculator (ETC) for a telescope-detector system in the near-infrared.
#	The detector is assumed to be housed in a cryostat. 
#	
#	The returned SNR is per pixel (for now).
#	
#	The user specifies the exposure time, the surface brightness (in Vega or AB magnitudes)
#	and the imaging band (J, H or K).
#
#	TO DO:
#	- double check: do we need Tr_win for the telescope thermal emission calcs?
#
###########################################################################################

# Importing detector and telescope properties
import apdParameters as detector
import anu23mParameters as telescope
import cryoParameters as cryo

# Required packages
import scipy.constants as constants
import scipy.integrate as integrate
import numpy as np
import pdb
import matplotlib.pyplot as plt

# Custom packages
from thermalEmissionIntensity import *

# NOTE: 
#	[Sigma] = electrons/pixel/s
#	[sigma] = electrons total

def exposureTimeCalc(
		band = 'H',
		t_exp = 0.1,
		surfaceBrightness = 19,
		magnitudeSystem = 'AB'
	):

	wavelength_eff = telescope.filter_bands_m[band][0]
	bandwidth = telescope.filter_bands_m[band][1]
	wavelength_min = telescope.filter_bands_m[band][2]
	wavelength_max = telescope.filter_bands_m[band][3]

	E_photon = constants.h * constants.c / wavelength_eff
	# Vega band magnitudes calculated using data from https://www.astro.umd.edu/~ssm/ASTR620/mags.html
	# Note: the bandwidths used to calculate these numbers DO NOT correspond to those in our system but are
	# slightly different. Hence there is some inaccuracy involved in using Vega magnitudes as the input.
	Vega_magnitudes = {
		'J' : 49.46953099,
		'H' : 49.95637318,
		'K' : 50.47441871
	}

	""" Telescope-detector system properties """
	# Calculate the plate scale.
	plate_scale_as = 206256/41554.86 * 1e3 * detector.l_px
	plate_scale_rad = plate_scale_as / 3600 * np.pi / 180
	Omega_px_rad = plate_scale_rad * plate_scale_rad
	T_sky = 273

	#########################################################################################################
	# Noise terms in the SNR calculation
	#########################################################################################################
	
	""" Signal photon flux """
	# Given the surface brightness, calculate the source electrons/s/pixel.
	m = surfaceBrightness	
	if magnitudeSystem == 'AB':
		F_nu_cgs = np.power(10, - (48.6 + m) / 2.5) 						# ergs/s/cm^2/arcsec^2/Hz		
	elif magnitudeSystem == 'Vega':
		F_nu_cgs = np.power(10, - (Vega_magnitudes[band] + m) / 2.5) 		# ergs/s/cm^2/arcsec^2/Hz
	else:
		print('Magnitude must be specified either in AB or Vega magnitudes!')

	F_lambda_cgs = F_nu_cgs * constants.c / np.power(wavelength_eff, 2)	# ergs/s/cm^2/arcsec^2/m
	F_lambda = F_lambda_cgs * 1e-7 * 1e4								# J/s/m^2/arcsec^2/m
	F_total_phot = F_lambda * bandwidth	/ E_photon						# photons/s/m^2/arcsec^2
	Sigma_source_phot = F_total_phot * np.power(plate_scale_as,2) * telescope.A_collecting	# photons/s/px
	Sigma_source_e = Sigma_source_phot * telescope.tau * detector.qe * detector.gain_av # electrons/s/px
	# pdb.set_trace()	
	
	""" Cryostat photon flux """
	Sigma_cryo = thermalEmissionIntensity(
		T = cryo.T,
		A = detector.A_px,
		wavelength_min = 0.0,
		wavelength_max = detector.wavelength_cutoff,
		Omega = cryo.Omega,
		eps = cryo.eps_wall,
		eta = detector.gain_av * detector.qe
		)

	""" Other background noise sources """
	if band == 'K':
		# In the K band, thermal emission from the sky 
		""" Telescope thermal background photon flux """
		# NOTE: the following are in units of photons/s/px
		# Mirrors (acting as grey bodies)
		I_M1 = thermalEmissionIntensity(T = telescope.T, wavelength_min = wavelength_min, wavelength_max = wavelength_max, Omega = Omega_px_rad, A = telescope.A_M1_total, eps = telescope.eps_M1_eff)
		I_M2 = thermalEmissionIntensity(T = telescope.T, wavelength_min = wavelength_min, wavelength_max = wavelength_max, Omega = Omega_px_rad, A = telescope.A_M2_total_eff, eps = telescope.eps_M2_eff)
		I_M3 = thermalEmissionIntensity(T = telescope.T, wavelength_min = wavelength_min, wavelength_max = wavelength_max, Omega = Omega_px_rad, A = telescope.A_M1_total, eps = telescope.eps_M1_eff)
		# Spider (acting as a grey body at both the sky temperature and telescope temperature)
		I_spider = \
				thermalEmissionIntensity(T = telescope.T, 	wavelength_min = wavelength_min, wavelength_max = wavelength_max, Omega = Omega_px_rad, A = telescope.A_M1_total, eps = telescope.eps_spider_eff)\
			  + thermalEmissionIntensity(T = T_sky, 		wavelength_min = wavelength_min, wavelength_max = wavelength_max, Omega = Omega_px_rad, A = telescope.A_M1_total, eps = 1 - telescope.eps_spider_eff)
		# Cryostat window (acting as a grey body)
		I_window = thermalEmissionIntensity(T = cryo.T, wavelength_min = wavelength_min, wavelength_max = wavelength_max, Omega = Omega_px_rad, A = telescope.A_M1_total, eps = cryo.eps_win)

		# Multiply by the gain and QE to get units of electrons/s/px.
		# We don't multiply by the transmission because the mirrors themselves are emitting.
		Sigma_tel = detector.gain_av * detector.qe * (I_M1 + I_M2 + I_M3 + I_spider + I_window)

		""" Sky thermal background photon flux """
		# Atmospheric properties
		
		f = open('cptrans_zm_23_10.dat','r')
		wavelengths_sky = [];
		Tr_sky = [];
		for line in f:
			cols = line.split()
			wavelengths_sky.append(float(cols[0]))
			Tr_sky.append(float(cols[1]))
		Tr_sky = np.asarray(Tr_sky)
		wavelengths_sky = np.asarray(wavelengths_sky) * 1e-6
		eps_sky = lambda wavelength: np.interp(wavelength, wavelengths_sky, 1 - Tr_sky)
		f.close()

		Sigma_sky_phot = thermalEmissionIntensity(
			T = T_sky, 
			wavelength_min = wavelength_min, 
			wavelength_max = wavelength_max, 
			Omega = Omega_px_rad, 
			A = telescope.A_M1_reflective, 
			eps = eps_sky
			)

		# Multiply by the gain, QE and telescope transmission to get units of electrons/s/px.
		Sigma_sky = detector.gain_av * detector.qe * telescope.tau * Sigma_sky_phot

		Sigma_sky = Sigma_sky + Sigma_tel

	else:
		# In the J and H bands, OH emission dominates; hence empirical sky brightness values are used instead.
		""" Empirical sky background flux """
		F_sky_nu_cgs = np.power(10, -(telescope.sky_brightness[band] + 48.60)/2.5)
		F_sky_lambda_cgs = F_sky_nu_cgs * constants.c / np.power(wavelength_eff,2)
		F_sky_lambda = F_sky_lambda_cgs * 1e-7 * 1e4
		F_sky_total_phot = F_sky_lambda * bandwidth / E_photon
		Sigma_sky_phot = F_sky_total_phot * np.power(plate_scale_as,2) * telescope.A_collecting	# photons/s/px
		Sigma_sky = detector.gain_av * detector.qe * telescope.tau * Sigma_sky_phot # electrons/s/px

	""" Dark current """
	Sigma_dark = detector.dark_current

	#########################################################################################################
	# Calculating the SNR
	#########################################################################################################
	N_source = Sigma_source_e * t_exp
	N_dark = Sigma_dark * t_exp
	N_cryo = Sigma_cryo * t_exp
	N_sky = Sigma_sky * t_exp
	N_RN = detector.read_noise * detector.read_noise

	SNR = N_source / np.sqrt(N_source + N_dark + N_cryo + N_sky + N_RN)

	#########################################################################################################

	etc_output = {
		# Input parameters
		't_exp' : t_exp,
		'band' : band,
		'surfaceBrightness' : surfaceBrightness,
		'magnitudeSystem' : magnitudeSystem,
		# Noise standard deviations
		'sigma_source' : np.sqrt(N_source),
		'sigma_dark' : np.sqrt(N_dark),
		'sigma_cryo' : np.sqrt(N_cryo),
		'sigma_sky' : np.sqrt(N_sky),
		'sigma_RN' : detector.read_noise,
		# Noise variances
		'N_source' : N_source,
		'N_dark' : N_dark,
		'N_cryo' : N_cryo,
		'N_sky' : N_sky,
		'N_RN' : N_RN,
		# SNR
		'SNR' : SNR
	}

	return etc_output

#########################################################################################################


