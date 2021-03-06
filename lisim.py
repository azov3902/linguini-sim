################################################################################
#
# 	File:		lisim.py
#	Author:		Anna Zovaro
#	Email:		anna.zovaro@anu.edu.au
#
#	Description:
#	A module for simulating lucky imaging.
#
#	Copyright (C) 2016 Anna Zovaro
#
#	Lucky imaging techniques to implement:
#	- Shifting-and-stacking via
#		- Cross-correlation
#		- Aligning to brightest pixel
#		- Drizzle algorithm for image alignment (sub-integer alignment)
#
#	- Frame selection techniques:
#		- Rank in order of brightest pixel value
#		- Cross-correlate the ideal PSF (say, Airy disc) with a subsection of the image containing a guide star--peak of the x-corr indicates the correlation (basically the Strehl) whilst its position gives the shift that needs to be applied 
#		- Rank in order of the fraction of light concentrated in the brightest pixel of the guide star PSF
#
################################################################################
#
#	This file is part of linguinesim.
#
#	linguinesim is free software: you can redistribute it and/or modify
#	it under the terms of the GNU General Public License as published by
#	the Free Software Foundation, either version 3 of the License, or
#	(at your option) any later version.
#
#	linguinesim is distributed in the hope that it will be useful,
#	but WITHOUT ANY WARRANTY; without even the implied warranty of
#	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#	GNU General Public License for more details.
#
#	You should have received a copy of the GNU General Public License
#	along with linguinesim.  If not, see <http://www.gnu.org/licenses/>.
#
################################################################################
from __future__ import division, print_function
import miscutils as mu
import numpy as np
import ipdb
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm 
from matplotlib import rc
from matplotlib.cbook import is_numlike
from matplotlib.mlab import normpdf
rc('image', interpolation='none', cmap = 'binary_r')

import scipy.signal
import scipy.ndimage.interpolation
from scipy.ndimage import center_of_mass
import astropy.modeling
import pyfftw

# Multithreading/processing packages
from functools import partial
from multiprocessing.dummy import Pool as ThreadPool	# dummy = Threads
from multiprocessing import Pool as ProcPool			# no dummy = Processes
import time

# linguine modules 
from linguineglobals import *
import fftwconvolve, obssim, etcutils, imutils

################################################################################
def lucky_frame(
	im, 							# In electron counts/s.
	psf, 							# Normalised.
	scale_factor, 					
	t_exp, 
	final_sz,
	tt = np.array([0, 0]),
	im_star = None,					# In electron counts/s.					
	noise_frame_gain_multiplied = 0,		# Noise injected into the system that is multiplied up by the detector gain after conversion to counts via a Poisson distribution, e.g. sky background, emission from telescope, etc. Must have shape final_sz. It is assumed that this noise frame has already been multiplied up by the detector gain!
	noise_frame_post_gain = 0,		# Noise injected into the system after gain multiplication, e.g. read noise. Must have shape final_sz.
	gain = 1,						# Detector gain.
	detector_saturation=np.inf,		# Detector saturation.
	plate_scale_as_px_conv = 1,		# Only used for plotting.
	plate_scale_as_px = 1,			# Only used for plotting.
	plotit=False):
	""" 
		This function can be used to generate a short-exposure 'lucky' image that can be input to the Lucky Imaging algorithms.
			Input: 	one 'raw' countrate image of a galaxy; one PSF with which to convolve it (at the same plate scale)
			Output: a 'Lucky' exposure. 			
			Process: convolve with PSF --> resize to detector --> add tip and tilt (from a premade vector of tip/tilt values) --> convert to counts --> add noise --> subtract the master sky/dark current. 
	"""	
	# Convolve with PSF.
	im_raw = im
	im_convolved = obssim.convolve_psf(im_raw, psf)

	# Add a star to the field. We need to add the star at the convolution plate scale BEFORE we resize down because of the tip-tilt adding step!
	if is_numlike(im_star):
		if im_star.shape != im_convolved.shape:
			print("ERROR: the input image of the star MUST have the same size and plate scale as the image of the galaxy after convolution!")
			raise UserWarning
		im_convolved += im_star

	# Resize to detector (+ edge buffer).
	im_resized = imutils.fourier_resize(
		im = im_convolved,
		scale_factor = scale_factor,
		conserve_pixel_sum = True)

	# Add tip and tilt. To avoid edge effects, max(tt) should be less than or equal to the edge buffer.
	edge_buffer_px = (im.shape[0] - final_sz[0]) / 2
	if edge_buffer_px > 0 and max(tt) > edge_buffer_px:
		print("WARNING: the edge buffer is less than the supplied tip and tilt by a margin of {:.2f} pixels! Shifted image will be clipped.".format(np.abs(edge_buffer_px - max(tt))))
	im_tt = obssim.add_tt(image = im_resized, tt_idxs = tt)[0]	
	# Crop back down to the detector size.
	if edge_buffer_px > 0:
		im_tt = imutils.centre_crop(im_tt, final_sz)	
	# Convert to counts. Note that we apply the gain AFTER we convert to integer
	# counts.
	im_counts = etcutils.expected_count_to_count(im_tt, t_exp = t_exp) * gain
	# Add the pre-gain noise. Here, we assume that the noise frame has already 
	# been multiplied by the gain before being passed into this function.
	im_noisy = im_counts + noise_frame_gain_multiplied
	# Add the post-gain noise (i.e. read noise)
	im_noisy += noise_frame_post_gain
	# Account for detector saturation
	im_noisy = np.clip(im_noisy, a_min=0, a_max=detector_saturation)

	if plotit:
		plate_scale_as_px = plate_scale_as_px_conv * scale_factor
		# Plotting
		mu.newfigure(1,3)
		plt.suptitle('Convolving input image with PSF and resizing to detector')
		mu.astroimshow(im=im_raw, 
			title='Truth image (electrons/s)', 
			plate_scale_as_px = plate_scale_as_px_conv, 
			colorbar_on=True, 
			subplot=131)
		mu.astroimshow(im=psf, 
			title='Point spread function (normalised)', 
			plate_scale_as_px = plate_scale_as_px_conv, 
			colorbar_on=True, 
			subplot=132)
		# mu.astroimshow(im=im_convolved, 
		# 	title='Star added, convolved with PSF (electrons/s)', 
		# 	plate_scale_as_px = plate_scale_as_px_conv, 
		# 	colorbar_on=True, 
		# 	subplot=143)
		mu.astroimshow(im=im_resized, 
			title='Resized to detector plate scale (electrons/s)', 
			plate_scale_as_px=plate_scale_as_px, 
			colorbar_on=True, 
			subplot=133)

		# Zooming in on the galaxy
		# mu.newfigure(1,4)
		# plt.suptitle('Convolving input image with PSF and resizing to detector')
		# mu.astroimshow(im=imutils.centre_crop(im=im_raw, units='arcsec', plate_scale_as_px=plate_scale_as_px_conv, sz_final=(6, 6)), title='Raw input image (electrons/s)', plate_scale_as_px = plate_scale_as_px_conv, colorbar_on=True, subplot=141)
		# mu.astroimshow(im=psf, title='Point spread function (normalised)', plate_scale_as_px = plate_scale_as_px_conv, colorbar_on=True, subplot=142)
		# mu.astroimshow(im=imutils.centre_crop(im=im_convolved, units='arcsec', plate_scale_as_px=plate_scale_as_px_conv, sz_final=(6, 6)), title='Star added, convolved with PSF (electrons/s)', plate_scale_as_px = plate_scale_as_px_conv, colorbar_on=True, subplot=143)
		# mu.astroimshow(im=imutils.centre_crop(im=im_resized, units='arcsec', plate_scale_as_px=plate_scale_as_px, sz_final=(6, 6)), title='Resized to detector plate scale (electrons/s)', plate_scale_as_px=plate_scale_as_px, colorbar_on=True, subplot=144)

		mu.newfigure(1,3)
		plt.suptitle('Adding tip and tilt, converting to integer counts and adding noise')
		mu.astroimshow(im=im_tt, 
			title='Atmospheric tip and tilt added (electrons/s)', 
			plate_scale_as_px=plate_scale_as_px, 
			colorbar_on=True,
			subplot=131)
		mu.astroimshow(im=im_counts, 
			title=r'Converted to integer counts and gain-multiplied by %d (electrons)' % gain, 
			plate_scale_as_px=plate_scale_as_px, 
			colorbar_on=True, 
			subplot=132)
		mu.astroimshow(im=im_noisy, 
			title='Noise added (electrons)', 
			plate_scale_as_px=plate_scale_as_px, 
			colorbar_on=True, 
			subplot=133)

		# plt.subplot(1,4,4)
		plt.figure()
		x = np.linspace(-im_tt.shape[0]/2, +im_tt.shape[0]/2, im_tt.shape[0]) * plate_scale_as_px
		plt.plot(x, im_tt[:, im_tt.shape[1]/2], 'g', label='Electron count rate')
		plt.plot(x, im_counts[:, im_tt.shape[1]/2], 'b', label='Converted to integer counts ($t_{exp} = %.2f$ s)' % t_exp)
		plt.plot(x, im_noisy[:, im_tt.shape[1]/2], 'r', label='Noise added')
		plt.xlabel('arcsec')
		plt.ylabel('Pixel value (electrons)')
		plt.title('Linear profiles')
		plt.axis('tight')
		plt.legend(loc='lower left')
		mu.show_plot()

	return im_noisy

################################################################################
def shift_pp(image, img_ref_peak_idx, fsr, bid_area):
	if type(image) == list:
		image = np.array(image)	

	# Search in the bid area of the input image for the peak pixel coordinates.
	if bid_area:
		sub_image = imutils.rotateAndCrop(image_in_array = images, cropArg = bid_area)
	else:
		sub_image = image		
	img_peak_idx = np.asarray(np.unravel_index(np.argmax(sub_image), sub_image.shape))	

	# Shift the image by the relative amount.
	rel_shift_idx = (img_ref_peak_idx - img_peak_idx)
	image_shifted = scipy.ndimage.interpolation.shift(image, rel_shift_idx)

	peak_pixel_val = max(sub_image.flatten())	# Maximum pixel value (for now, not used)

	return image_shifted, -rel_shift_idx, peak_pixel_val

################################################################################
def shift_centroid(image, img_ref_peak_idx, centroid_threshold):
	if type(image) == list:
		image = np.array(image)

	# # Thresholding the image
	image_subtracted_bg = np.copy(image)
	# image_subtracted_bg[image<1.5*np.mean(image.flatten())] = 0
	# image -= min(image.flatten())

	image_subtracted_bg[image < centroid_threshold * max(image.flatten())] = 0
	img_peak_idx = _centroid(image_subtracted_bg)

	# Shift the image by the relative amount.
	rel_shift_idx = (img_ref_peak_idx - img_peak_idx)
	image_shifted = scipy.ndimage.interpolation.shift(image, rel_shift_idx)

	return image_shifted, -rel_shift_idx

################################################################################
def shift_xcorr(image, image_ref, buff_xcorr, sub_pixel_shift):
	if type(image) == list:
		image = np.array(image)
	
	# Subtracting the mean of each image
	image_subtracted_bg = image - np.mean(image.flatten())
	image_ref_subtracted_bg = image_ref - np.mean(image_ref.flatten())

	height, width = image.shape
	# if fftwconvolve.NTHREADS==0:
	corr = scipy.signal.fftconvolve(image_ref_subtracted_bg, image_subtracted_bg[::-1,::-1], 'same')
	# else:
		# corr = fftwconvolve.fftconvolve(image_ref_subtracted_bg, image_subtracted_bg[::-1,::-1], 'same')
	corr /= max(corr.flatten())	# The fitting here does not work if the pixels have large values!
	
	if sub_pixel_shift: 
		# Fitting a Gaussian.
		Y, X = np.mgrid[-(height-2*buff_xcorr)/2:(height-2*buff_xcorr)/2, -(width-2*buff_xcorr)/2:(width-2*buff_xcorr)/2]
		x_peak, y_peak = np.unravel_index(np.argmax(corr), corr.shape)
		try:		
			p_init = astropy.modeling.models.Gaussian2D(x_mean=X[x_peak,y_peak],y_mean=Y[x_peak,y_peak],x_stddev=5.,y_stddev=5.,amplitude=np.max(corr.flatten()))
		except:			
			p_init = astropy.modeling.models.Gaussian2D(x_mean=x_peak,y_mean=y_peak,x_stddev=1.,y_stddev=1.,amplitude=1.)
		fit_p = astropy.modeling.fitting.LevMarLSQFitter()
		p_fit = fit_p(p_init, X, Y, corr[buff_xcorr:height-buff_xcorr, buff_xcorr:width-buff_xcorr])
		rel_shift_idx = (p_fit.y_mean.value, p_fit.x_mean.value)	# NOTE: the indices have to be swapped around here for some reason!		
	else:
		rel_shift_idx = np.unravel_index(np.argmax(corr), corr.shape)
		rel_shift_idx = (rel_shift_idx[0] - height/2, rel_shift_idx[1] - width/2)
	
	# mu.newfigure(2,2)
	# mu.astroimshow(im=image, title='Input image', subplot=221)
	# mu.astroimshow(im=image_ref, title='Reference image', subplot=222)
	# mu.astroimshow(im=corr, title='Cross-correlation', subplot=223)
	# mu.astroimshow(im=p_fit(X,Y), title='Gaussian fit', subplot=224)
	# mu.show_plot()

	image_shifted = scipy.ndimage.interpolation.shift(image, rel_shift_idx)	

	return image_shifted, tuple(-x for x in rel_shift_idx)

################################################################################
def shift_gaussfit(image, img_ref_peak_idx):
	if type(image) == list:
		image = np.array(image)

	# Subtracting the mean of the input image
	image_subtracted_bg = image - np.mean(image.flatten())

	# Fitting a Gaussian to the mean-subtracted image.
	peak_idx = _gaussfit_peak(image_subtracted_bg)	
	rel_shift_idx = -(peak_idx - img_ref_peak_idx)

	image_shifted = scipy.ndimage.interpolation.shift(image, rel_shift_idx)	

	return image_shifted, tuple(-x for x in rel_shift_idx)

################################################################################
def lucky_imaging(images, li_method, 
	mode = 'serial',		# whether or not to process images in parallel
	image_ref = None,		# reference image
	fsr = 1,				# for peak pixel/FAS method
	bid_area = None,		# for peak pixel method
	N = None,
	centroid_threshold = 0.25,	# for centroiding method
	sub_pixel_shift = True,	# for xcorr/FAS method
	buff_xcorr = 25, 		# for xcorr/FAS method
	buff_fas = 32,			# for FAS method (edge ramp buffer)
	cutoff_freq_frac = 1,	# for FAS method
	sigma_kernel = 0,		# for FAS method (sigma of Gaussian filter)
	use_vals_outside_cutoff_freq = True,	# for FAS method
	stacking_method = 'average',
	timeit = True
	):
	""" 
		Apply a Lucky Imaging (LI) technique to a sequence of images stored in the input array images. 
		The type of LI technique used is specified by input string type and any additional arguments which may be required are given in vararg.
	"""
	tic = time.time()
	images, image_ref, N = _li_error_check(images, image_ref, N)
	if not timeit:
		print("Applying Lucky Imaging technique '{}' to input series of {:d} images...".format(li_method, N))
	
	# For each of these functions, the output must be of the form 
	#	image_shifted, rel_shift_idxs	
	li_method = li_method.lower()
	if li_method == 'cross-correlation':
		shift_fun = partial(shift_xcorr, image_ref=image_ref, buff_xcorr=buff_xcorr, sub_pixel_shift=sub_pixel_shift)	
	elif li_method == 'gaussian fit':
		img_ref_peak_idx = _gaussfit_peak(image_ref - np.mean(image_ref.flatten()))
		shift_fun = partial(shift_gaussfit, 
			img_ref_peak_idx=img_ref_peak_idx)

	elif li_method == 'peak pixel':
		# Determining the reference coordinates.
		if bid_area:			
			sub_image_ref = imutils.centre_crop(image_ref, bid_area)
		else:
			sub_image_ref = image_ref
		img_ref_peak_idx = np.asarray(np.unravel_index(np.argmax(sub_image_ref), sub_image_ref.shape)) 
		shift_fun = partial(shift_pp, 
			img_ref_peak_idx=img_ref_peak_idx, 
			bid_area=bid_area, 
			fsr=fsr)

	elif li_method == 'centroid':
		image_ref_subtracted_bg = np.copy(image_ref)
		image_ref_subtracted_bg[image_ref < centroid_threshold * max(image_ref.flatten())] = 0
		img_ref_peak_idx = _centroid(image_ref_subtracted_bg)
		shift_fun = partial(shift_centroid, 
			img_ref_peak_idx=img_ref_peak_idx, 
			centroid_threshold=centroid_threshold)	

	elif li_method == 'blind stack':
		if stacking_method == 'median combine':			
			arr = np.ndarray((1, image_ref.shape[0], image_ref.shape[1]))
			arr[0,:] = image_ref
			image_ref = arr
			image_stacked = obssim.median_combine(np.concatenate((image_ref, images)))
		elif stacking_method == 'average':
			image_stacked = (image_ref + np.sum(images, axis=0)) / (N + 1)	
		rel_shift_idxs = np.zeros( (N, 2) )
		return image_stacked, rel_shift_idxs

	elif li_method == 'fourier amplitude selection' or li_method =='fas':
		# Need to shift each image.
		shift_fun = partial(shift_xcorr, 
			image_ref=image_ref, 
			buff_xcorr=buff_xcorr, 
			sub_pixel_shift=sub_pixel_shift)
		# THEN we need to apply the Fourier amplitude selection technique.
	else:
		print("ERROR: invalid Lucky Imaging method '{}' specified; must be 'cross-correlation', 'peak pixel', 'centroid' or 'Gaussian fit' for now...".format(li_method))
		raise UserWarning

	# In here, want to parallelise the processing for *each image*. So make 
	# shift functions that work on a single image and return the shifted image, 
	# then stack it out here.
	if mode == 'parallel':
		# Setting up to execute in parallel.
		images = images.tolist()	# Need to convert the image array to a list.

		# Executing in parallel.
		pool = ProcPool()
		results = pool.map(shift_fun, images, 1)
		pool.close()
		pool.join()

		# Extracting the output arguments.
		images_shifted = np.array(zip(*results)[0]) 
		rel_shift_idxs = np.array(zip(*results)[1])
		if li_method == 'peak pixel' and fsr < 1:
			peak_pixel_vals = np.array(zip(*results)[2])

	elif mode == 'serial':
		# Loop through each image individually.
		images_shifted = np.zeros( (N, image_ref.shape[0], image_ref.shape[1]) )	
		rel_shift_idxs = np.zeros( (N, 2) )
		for k in range(N):
			if li_method == 'peak pixel':
				if k == 0:
					peak_pixel_vals = np.zeros(N)
				images_shifted[k], rel_shift_idxs[k], peak_pixel_vals[k] = shift_fun(image=images[k])
			else:
				images_shifted[k], rel_shift_idxs[k] = shift_fun(image=images[k])
	else:
		print("ERROR: mode must be either parallel or serial!")
		raise UserWarning

	# If we're using an FSR < 1 in the peak pixel method, then we must do the following:
	#	1. Get our method to return a list of peak pixel values.
	#	2. Sort that list in descending order and get the indices of the corresponding images in the range [0, FSR * N)
	#	3. Add these images together. 
	if li_method == 'peak pixel' and fsr < 1:
		sorted_idx = np.argsort(peak_pixel_vals)[::-1]	# Array holding indices of images
		N = np.ceil(fsr * N)
		# Is averaging the best way to do this? Probably not...
		if stacking_method == 'median combine':
			arr = np.ndarray((1, image_ref.shape[0], image_ref.shape[1]))
			arr[0,:] = image_ref
			image_ref = arr
			image_stacked = obssim.median_combine(
				np.concatenate((image_ref, images_shifted[sorted_idx[:N]])))
		elif stacking_method == 'average':
			image_stacked = (image_ref + \
				np.sum(images_shifted[sorted_idx[:N]], 0)) / (N + 1)

	elif li_method == 'fourier amplitude selection' or li_method =='fas':
		# From Mackay 2013: within the cutoff spatial frequency radius, we 
		# select (u,v) pixels by using the Fourier amplitude. Outside this 
		# cutoff frequency, we select (u,v) pixels by using the peak pixel value 
		# in the image.

		# Linearly ramp the images to zero.
		images_shifted = edge_ramp(images_shifted, buff_fas)

		h, w = image_ref.shape
		N_frames_to_keep = max(1, int(np.round(fsr * N)))
		images_fft = pyfftw.interfaces.numpy_fft.fftshift(
			pyfftw.interfaces.numpy_fft.fft2(images_shifted), 
			axes=(1,2))

		cutoff_freq_px = int(np.round(cutoff_freq_frac * min(h,w)))
		U,V = np.meshgrid(np.linspace(-w/2,w/2-1,w),np.linspace(-h/2,h/2-1,h))
		uv_map = np.zeros( (h,w) )
		uv_map[np.sqrt(U**2 + V**2) < cutoff_freq_px]=1
		fft_sum = np.zeros( (h, w), dtype=complex )
		
		# OUTSIDE THE CUTOFF FREQUENCY
		if use_vals_outside_cutoff_freq:			
			# Step 1. Sort the images in order of peak pixel value.
			max_pixel_vals = np.max(images_shifted,axis=(1,2))
			idxs_to_keep = np.argsort(max_pixel_vals)[-N_frames_to_keep:]
			# Step 2. 
			vals_to_keep=np.zeros( (h, w, N_frames_to_keep), dtype=complex )
			for u, v in zip(V[uv_map==0],U[uv_map==0]):
				# For these coordinates, grab the indices of the N highest 
				# values in the data cube.
				try:
					vals_to_keep[u+h/2,v+w/2] = images_fft[
						idxs_to_keep,
						u+h/2,
						v+w/2]
				except:
					ipdb.set_trace()
			fft_sum += np.sum(vals_to_keep, axis=2)

		# WITHIN THE CUTOFF FREQUENCY
		images_fft_amp = np.abs(images_fft)

		# Smoothing with a Gaussian kernel
		if sigma_kernel != 0:
			for k in range(images_fft_amp.shape[0]):
				images_fft_amp[k] = imutils.gaussian_smooth(
					im=images_fft_amp[k],
					sigma=sigma_kernel
					)

		# For now, don't worry about parallelisation.		
		vals_to_keep=np.zeros( (h, w, N_frames_to_keep), dtype=complex )
		idxs_to_keep=np.zeros( (h, w, N_frames_to_keep), dtype=int)	# Indices along the zeroth axis of the datacube indicating which frames' data we want to keep for the whole image
		for u, v in zip(V[uv_map==1],U[uv_map==1]):
			# For these coordinates, grab the indices of the N highest values in the data cube.
			idxs_to_keep[u+h/2,v+w/2] = np.argsort(
				images_fft_amp[:,u+h/2,v+w/2])[-N_frames_to_keep:]
			vals_to_keep[u+h/2,v+w/2] = images_fft[
				idxs_to_keep[u+h/2,v+w/2],
				u+h/2,
				v+w/2]
		# Take the sum along the zeroth axis and IFFT to get the reassembled image.
		fft_sum += np.sum(vals_to_keep, axis=2)

		image_stacked = np.abs(pyfftw.interfaces.numpy_fft.ifft2(
			pyfftw.interfaces.numpy_fft.fftshift(fft_sum/N_frames_to_keep)))
	else:
		# Now, stacking the images. Need to change N if FSR < 1.
		if stacking_method == 'median combine':			
			arr = np.ndarray((1, image_ref.shape[0], image_ref.shape[1]))
			arr[0,:] = image_ref
			image_ref = arr
			image_stacked = obssim.median_combine(np.concatenate(
				(image_ref, images_shifted)))
		elif stacking_method == 'average':
			image_stacked = (image_ref + np.sum(images_shifted, 0)) / (N + 1)	

	toc = time.time()
	if timeit:
		print("APPLYING LUCKY IMAGING TECHNIQUE {}: Elapsed time for {:d} {}-by-{} images in {} mode: {:.5f}".format(li_method, N, image_ref.shape[0], image_ref.shape[1], mode, (toc-tic)))

	return image_stacked, rel_shift_idxs

################################################################################
def alignment_err(in_idxs, out_idxs, opticalsystem,
	li_method='',
	plotHist=True,
	verbose=True):
	"""
		Compute the alignment errors arising in the Lucky Imaging shifting-and-stacking process given an input array of tip and tilt coordinates applied to the input images and the coordinates of the shifts applied in the shifting-and-stacking process.
	"""
	N = in_idxs.shape[0]
	errs_as = np.zeros( (N, 3) )
		
	for k in range(N):
		errs_as[k, 0] = (in_idxs[k,0] - out_idxs[k,0]) * opticalsystem.plate_scale_as_px
		errs_as[k, 1] = (in_idxs[k,1] - out_idxs[k,1]) * opticalsystem.plate_scale_as_px
		errs_as[k, 2] = np.sqrt(errs_as[k, 0]**2 + errs_as[k, 1]**2)
	errs_px = errs_as / opticalsystem.plate_scale_as_px
			
	# Print the alignment errors to screen.
	if verbose:
		print('------------------------------------------------')
		print('Tip/tilt coordinates\nInput\t\tOutput\t\tError\tError (arcsec)')
		print('------------------------------------------------')
		for k in range(N):
			print('(%6.2f,%6.2f)\t(%6.2f,%6.2f)\t%4.2f\t%4.2f' % (in_idxs[k,0],
				in_idxs[k,1],out_idxs[k,0],out_idxs[k,1],errs_px[k,2],
				errs_as[k,2]))
		print('------------------------------------------------')
		print('\t\t\tMean\t%4.2f' % np.mean(errs_as))

	if plotHist:
		plot_alignment_err_histogram(errs_as, li_method)
	
	return errs_as

################################################################################
def plot_alignment_err_histogram(errs_as,
	li_method=''):
	x_errs_as = errs_as[:,0]
	y_errs_as = errs_as[:,1]
	# Plot a pretty histogram showing the distribution of the alignment errors, and fit a Gaussian to them.
	range_as = 2 * max(max(np.abs(y_errs_as)), max(np.abs(x_errs_as)))
	nbins = int(errs_as.shape[0] / 100)
	mu.newfigure(1.5,1)
	plt.suptitle('{} Lucky Imaging shifting-and-stacking alignment errors'.format(li_method))

	plt.subplot(211)
	if nbins > 5:
		plt.hist(x_errs_as, bins=nbins, range=(-range_as/2,+range_as/2), normed=True)
	else:
		plt.hist(x_errs_as, range=(-range_as/2,+range_as/2), normed=True)
	mean_x = np.mean(x_errs_as)
	sigma_x = np.sqrt(np.var(x_errs_as))
	x = np.linspace(-range_as/2, range_as/2, 100)
	plt.plot(x, normpdf(x,mean_x,sigma_x), 'r', label=r'$\sigma_x$ = %.4f"' % (sigma_x))
	plt.title(r'$x$ alignment error')
	plt.xlabel('arcsec')
	plt.legend()

	plt.subplot(212)
	if nbins > 5:
		plt.hist(y_errs_as, bins=nbins, range=(-range_as/2,+range_as/2), normed=True)
	else:
		plt.hist(y_errs_as, range=(-range_as/2,+range_as/2), normed=True)
	mean_y = np.mean(y_errs_as)
	sigma_y = np.sqrt(np.var(y_errs_as))
	y = np.linspace(-range_as/2, range_as/2, 100)
	plt.plot(y, normpdf(y,mean_y,sigma_y), 'r', label=r'$\sigma_y$ = %.4f"' % (sigma_y))
	plt.title(r'$y$ alignment error')
	plt.xlabel('arcsec')
	plt.legend()	
	mu.show_plot()

################################################################################
def _li_error_check(images, 
	image_ref = None,
	N = None):
	"""
		A private method to be used to check the inputs to the Lucky Imaging methods. 
	"""
	# Need to convert to float if necessary.
	if type(images.flatten()[0]) != np.float64:
		images = images.astype(np.float64)
	if image_ref is not None and type(image_ref.flatten()[0]) != np.float64:
		image_ref = image_ref.astype(np.float64)

	# Checking image dimensions.
	if len(images.shape) > 4:
		print("WARNING: for now, please only input a 3D array of images to shift and stack! I'm only going to operate on the first set of images...")
		images = np.squeeze(images[0])	
	
	if len(images.shape) == 3:
		if N and N > images.shape[0]:
			print("ERROR: if specified, N must be equal to or less than the length of the first dimension of the images array.")
			raise UserWarning
		if image_ref is None:
			# If the reference image is not specified, we use the first image in the array as the reference: 
			# i.e. we align all other images to images[0].
			if not N:
				N = images.shape[0]-1
			image_ref = np.copy(images[0])
			images = np.copy(images[1:])	# Only need to go through images 1:N-1.
		else:
			if image_ref.shape != images[0].shape:
				print("ERROR: if specified, reference image shape must be equal to input image stack shape.")
				raise UserWarning
			if not N:
				N = images.shape[0]			
	else:
		# Error: cannot shift and stack a single image!
		print("ERROR: cannot shift and stack a single image! Input array must have N > 1.")
		raise UserWarning

	return images, image_ref, N

################################################################################
def _centroid(image):
	""" Returns the centroid coordinates of an image. """
	height = image.shape[0]
	width = image.shape[1]
	x = np.arange(height)
	y = np.arange(width)
	X, Y = np.meshgrid(y,x)
	M_10 = np.sum((X * image).flatten())
	M_01 = np.sum((Y * image).flatten())
	M_00 = np.sum(image.flatten())

	centroid = np.asarray([M_01 / M_00, M_10 / M_00])

	return centroid

################################################################################
def _gaussfit_peak(image):
	""" Returns the coordinates of the peak of a 2D Gaussian fitted to the 
		image. """
	height, width = image.shape

	# Fitting a Gaussian.
	Y, X = np.mgrid[-(height)/2:(height)/2, -(width)/2:(width)/2]
	try:		
		p_init = astropy.modeling.models.Gaussian2D(x_stddev=1.,y_stddev=1.)
	except:
		p_init = astropy.modeling.models.Gaussian2D(x_mean=1.,y_mean=1.,x_stddev=1.,y_stddev=1.,amplitue=1.)
	fit_p = astropy.modeling.fitting.LevMarLSQFitter()
	p_fit = fit_p(p_init, X, Y, image)		
	
	peak_idx = np.array([p_fit.y_mean.value, p_fit.x_mean.value])	# NOTE: the indices have to be swapped around here for some reason!		

	return peak_idx

################################################################################
def edge_ramp(im, buff):
	""" Linearly ramps the values of an image to zero over a buffer with width 
		buff at the edges of the each image. """
	buff = int(buff)

	# Crop the images by an amount buff_xcorr.
	if len(im.shape) == 3:
		_, h, w = im.shape
	else:
		h, w = im.shape
	im = imutils.centre_crop(im, (h-2*buff,w-2*buff))

	# Pad.
	if len(im.shape) == 3:
		im = np.pad(im, ( (0,0), (buff,buff), (buff,buff) ), mode='linear_ramp')	
	else:
		im = np.pad(im, buff, mode='linear_ramp')

	return im
