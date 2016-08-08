####################################################################################################
#
# 	File:		obssim.py
#	Author:		Anna Zovaro
#	Email:		anna.zovaro@anu.edu.au
#
#	Description:
#	A module for simulating imaging of objects using a given telescope and detector system.
#
#	Copyright (C) 2016 Anna Zovaro
#
####################################################################################################
#
#	This file is part of lingiune-sim.
#
#	lingiune-sim is free software: you can redistribute it and/or modify
#	it under the terms of the GNU General Public License as published by
#	the Free Software Foundation, either version 3 of the License, or
#	(at your option) any later version.
#
#	lingiune-sim is distributed in the hope that it will be useful,
#	but WITHOUT ANY WARRANTY; without even the implied warranty of
#	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#	GNU General Public License for more details.
#
#	You should have received a copy of the GNU General Public License
#	along with lingiune-sim.  If not, see <http://www.gnu.org/licenses/>.
#
####################################################################################################
from __future__ import division, print_function 
from apdsim import *

def airyDisc(wavelength_m, f_ratio, l_px_m, 
	detector_size_px=None,
	trapz_oversampling=8,	# Oversampling used in the trapezoidal rule approximation.
	coords=None,
	P_0=1,
	plotIt=False):
	"""
		Returns the PSF of an optical system with a circular aperture given the f ratio, pixel and detector size at a given wavelength_m.

		If desired, an offset (measured from the top left corner of the detector) can be specified in vector coords = (x, y).

		The PSF is normalised such that the sum of every pixel in the PSF (extended to infinity) is equal to P_0 (unity by default), where P_0 is the total energy incident upon the telescope aperture. 

		P_0 represents the *ideal* total energy in the airy disc (that is, the total energy incident upon the telescope aperture), whilst P_sum measures the actual total energy in the image (i.e. the pixel values). 
	"""

	# Output image size 
	detector_height_px, detector_width_px = detector_size_px[0:2]

	# Intensity map grid size
	# Oversampled image size
	oversampled_height_px = detector_height_px * trapz_oversampling
	oversampled_width_px = detector_width_px * trapz_oversampling
	# Coordinates of the centre of the Airy disc in the intensity map grid
	if coords == None:
		x_offset = oversampled_height_px/2
		y_offset = oversampled_width_px/2
	else:
		x_offset = coords[0] * trapz_oversampling
		y_offset = coords[1] * trapz_oversampling
	dx = oversampled_height_px/2 - x_offset
	dy = oversampled_width_px/2 - y_offset
	# Intensity map grid indices (in metres)
	x = np.arange(-oversampled_height_px//2, +oversampled_height_px//2 + oversampled_height_px%2 + 1, 1) + dx
	y = np.arange(-oversampled_width_px//2, +oversampled_width_px//2 + oversampled_width_px%2 + 1, 1) + dy
	x *= l_px_m / trapz_oversampling
	y *= l_px_m / trapz_oversampling
	Y, X = np.meshgrid(y, x)

	# Central intensity (W m^-2)
	I_0 = P_0 * np.pi / 4 / wavelength_m / wavelength_m / f_ratio / f_ratio

	# Calculating the Airy disc
	r = lambda x, y: np.pi / wavelength_m / f_ratio * np.sqrt(np.power(x,2) + np.power(y,2))
	I_fun = lambda x, y : np.power((2 * special.jv(1, r(x,y)) / r(x,y)), 2) * I_0 
	I = I_fun(X,Y)
	# I = np.swapaxes(I,0,1)
	nan_idx = np.where(np.isnan(I))
	if nan_idx[0].shape != (0,):
		I[nan_idx[0][0],nan_idx[1][0]] = I_0 # removing the NaN in the centre of the image if necessary

	""" Converting intensity values to count values in each pixel """
	# Approximation using top-hat intensity profile in each pixel
	count_approx = I * l_px_m**2 / trapz_oversampling**2
	count_approx = count_approx.astype(np.float64)

	# Approximation using trapezoidal rule
	count_cumtrapz = np.zeros((detector_height_px,detector_width_px))
	cumsum = 0
	for j in range(detector_width_px):
		for k in range(detector_height_px):
			px_grid = I[trapz_oversampling*k:trapz_oversampling*k+trapz_oversampling+1,trapz_oversampling*j:trapz_oversampling*j+trapz_oversampling+1]
			res1 = integrate.cumtrapz(px_grid, dx = l_px_m/trapz_oversampling, axis = 0, initial = 0)
			res2 = integrate.cumtrapz(res1[-1,:], dx = l_px_m/trapz_oversampling, initial = 0)
			count_cumtrapz[k,j] = res2[-1]
	# Total energy in image
	P_sum = sum(count_cumtrapz.flatten())
	count_cumtrapz /= P_sum

	if plotIt:
		mu.newfigure(1,2)
		plt.subplot(1,2,1)
		plt.imshow(I, norm=LogNorm())
		mu.colourbar()
		plt.title('Intensity (oversampled by a factor of %d)' % trapz_oversampling)
		plt.subplot(1,2,2)
		plt.imshow(count_cumtrapz, norm=LogNorm())
		mu.colourbar()
		plt.title('Count (via trapezoidal rule)')
		plt.show()

	return count_cumtrapz, I, P_0, P_sum, I_0

####################################################################################################
def psfKernel(wavelength_m, 
	l_px_m=None, 
	f_ratio=None,
	N_OS=None, 
	T_OS=8,
	detector_size_px=None,
	trunc_sigma=10.25,	# 10.25 corresponds to the 10th Airy ring		
	plotIt=False):
	"""
		Returns an Airy disc PSF corresponding to an optical system with a given f ratio, pixel size and detector size at a specified wavelength_m.

		If the detector size is not specified, then the PSF is truncated at a radius of 8 * sigma, where sigma corresponds to the HWHM (to speed up convolutions made using this kernel)

		There are two ways to constrain the plate scale of the output PSF. Either the f ratio or the Nyquist sampling factor (where a larger number ==> finer sampling) can be specified, but not both!
	"""	

	# Now, we have to calculate what the EFFECTIVE f ratio needs to be to achieve the desired Nyquist oversampling in the returned PSF.
	if not f_ratio:
		f_ratio = 2 * N_OS / wavelength_m * np.deg2rad(206265 / 3600) * l_px_m
	elif not N_OS:
		N_OS = wavelength_m * f_ratio / 2 / np.deg2rad(206265 / 3600) / l_px_m
		pdb.set_trace()	
	elif not l_px_m:
		l_px_m = wavelength_m * f_ratio / 2 / np.deg2rad(206265 / 3600) / N_OS	

	if not detector_size_px:
		psf_size = int(np.round(trunc_sigma * N_OS * 4))
		detector_size_px = (psf_size,psf_size)	

	# In the inputs to this function, do we need to specify the oversampling factor AND the f ratio and/or pixel widths?
	kernel = airyDisc(wavelength_m=wavelength_m, f_ratio=f_ratio, l_px_m=l_px_m, detector_size_px=detector_size_px, trapz_oversampling=T_OS, plotIt=plotIt)[0]	

	return kernel

####################################################################################################
def resizeImagesToDetector(images_raw, source_plate_scale_as, dest_plate_scale_as,
	dest_detector_size_px=None,
	plotIt=False):
	" Resize the images stored in array images_raw with a given plate scale to a detector with given dimensions and plate scale. "
	print("Resizing image(s) to detector...")

	# 1. Get the original size and shape of the input images.
	images_raw, N, source_height_px, source_width_px = getImageSize(images_raw)
	source_width_as = source_width_px * source_plate_scale_as
	source_height_as = source_height_px * source_plate_scale_as

	# If the destination plate scale is not specified, then we simply scale the dimensions of the input image appropriately.
	if not dest_detector_size_px:
		dest_detector_size_px = tuple(np.round(source_plate_scale_as / dest_plate_scale_as * x) for x in (source_height_px, source_width_px))

	# Getting the angular extent of the source image:
	# 	size(pixels on our detector) = size(of source, in as) / plate scale
	detector_height_px = dest_detector_size_px[0]
	detector_width_px = dest_detector_size_px[1]
	dest_width_px = source_width_as / dest_plate_scale_as
	dest_height_px = source_height_as / dest_plate_scale_as

	# Rescaling images to the appropriate size for our detector.
	images = np.ndarray((N, int(np.ceil(dest_height_px)), int(np.ceil(dest_width_px))))
	for k in range(N):
		im = Image.fromarray(images_raw[k])
		# NOTE: due to the way the Image package works, height and width indices are swapped
		im = im.resize((int(np.ceil(dest_width_px)), int(np.ceil(dest_height_px))), resample=PIL.Image.LANCZOS)
		images[k] = imageToArray(im)

	height_idx = 1	# Array index corresponding to image height.
	width_idx = 2	# Array index corresponding to image width.
		
	# Resizing to the size of the detector.
	if dest_height_px > detector_height_px:
		images = images[:, images.shape[height_idx]//2-detector_height_px//2:images.shape[height_idx]//2+detector_height_px//2, :]
		pad_height_top = 0
		pad_height_bottom = 0
	else:
		pad_height_top = np.floor((detector_height_px - images.shape[height_idx])/2.).astype(np.int)
		pad_height_bottom = np.ceil((detector_height_px - images.shape[height_idx])/2.).astype(np.int)

	if dest_width_px > detector_width_px:
		images = images[:, :, images.shape[width_idx]//2-detector_width_px//2:images.shape[width_idx]//2+detector_width_px//2]
		pad_width_left = 0
		pad_width_right = 0
	else: 
		pad_width_left = np.floor((detector_width_px - images.shape[width_idx])/2.).astype(np.int)
		pad_width_right = np.ceil((detector_width_px - images.shape[width_idx])/2.).astype(np.int)

	# Padding the resized images if necessary.
	images = np.pad(images, ((0, 0), (pad_height_top, pad_height_bottom), (pad_width_left, pad_width_right)), mode='constant')

	if plotIt:
		mu.newfigure(1,2)
		plt.subplot(1,2,1)
		plt.imshow(images_raw[0])
		mu.colourbar()
		plt.title('Input image')
		plt.subplot(1,2,2)
		plt.imshow(images[0])
		mu.colourbar()
		plt.title('Resized image')
		plt.suptitle('Resizing truth image to detector')
		plt.show()

	return np.squeeze(images)

###################################################################################
def getDiffractionLimitedImage(image_truth, l_px_m, f_ratio, wavelength_m, 
	f_ratio_in=None, wavelength_in_m=None, # f-ratio and imaging wavelength of the input image (if it has N_os > 1)
	N_OS_psf=4,
	detector_size_px=None,
	plotIt=False):
	""" Convolve the PSF of a given telescope at a given wavelength with image_truth to simulate diffraction-limited imaging. 
	It is assumed that the truth image has the appropriate plate scale of, but may be larger than, the detector. 
	If the detector size is not given, then it is assumed that the input image and detector have the same dimensions. 

	The flow should really be like this:
		1. Generate the PSF with N_OS = 4, say.
		2. Rescale the image to achieve the same plate scale.
		3. Convolve.
		4. Resample back down to the original plate scale.

	"""
	print("Diffraction-limiting truth image(s)...")
	image_truth, N, height, width = getImageSize(image_truth)

	# If the input image is already sampled by N_os > 1, then the PSF that we convolve with the image needs to add in quadrature with the PSF that has already been convolved with the image to get to the scaling we want.
	if f_ratio_in != None and wavelength_in_m != None:
		# Then we need to add the PSFs in quadrature.
		f_ratio_out = f_ratio
		wavelength_out_m = wavelength_m

		efl = 1
		D_in = efl / f_ratio_in
		D_out = efl / f_ratio_out
		FWHM_in = wavelength_in_m / D_in
		FWHM_out = wavelength_out_m / D_out
		FWHM_prime = np.sqrt(FWHM_out**2 - FWHM_in**2)

		wavelength_prime_m = wavelength_in_m
		D_prime = wavelength_prime_m / FWHM_prime
		f_ratio_prime = efl / D_prime

		f_ratio = f_ratio_prime
		wavelength_m = wavelength_prime_m

	# Because we specify the PSF in terms of Nyquist sampling, we need to express N_OS in terms of the f ratio and wavelength of the input image.
	N_OS_input = wavelength_m * f_ratio / 2 / l_px_m / (np.deg2rad(206265 / 3600))

	# Calculating the PSF
	psf = psfKernel(wavelength_m=wavelength_m, N_OS=N_OS_psf, l_px_m=l_px_m)
	# TODO need to check that the PSF is not larger than image_truth_large

	# Convolving the PSF and the truth image to obtain the simulated diffraction-limited image
	# image_difflim = np.ndarray((N, height, width))
	for k in range(N):
		# Resample the image up to the appropriate plate scale.
		image_truth_large = resizeImagesToDetector(image_truth[k], 1/N_OS_input, 1/N_OS_psf)
		# Convolve with the PSF.
		image_difflim_large = signal.fftconvolve(image_truth_large, psf, mode='same')
		# Resize the image to its original plate scale.
		if k == 0:
			im = resizeImagesToDetector(image_difflim_large, 1/N_OS_psf, 1/N_OS_input)
			image_difflim = np.ndarray((N, im.shape[0], im.shape[1]))
			image_difflim[0] = im
		else:
			image_difflim[k] = resizeImagesToDetector(image_difflim_large, 1/N_OS_psf, 1/N_OS_input)


	if plotIt:
		mu.newfigure(1,3)
		plt.subplot(1,3,1)
		plt.imshow(psf)
		mu.colourbar()
		plt.title('Diffraction-limited PSF of telescope')
		plt.subplot(1,3,2)
		plt.imshow(image_truth[0])
		mu.colourbar()
		plt.title('Truth image')
		plt.subplot(1,3,3)
		plt.imshow(image_difflim[0])
		mu.colourbar()
		plt.title('Diffraction-limited image')
		plt.suptitle('Diffraction-limiting image')
		plt.show()

	return np.squeeze(image_difflim)

####################################################################################################
def getSeeingLimitedImage(images, seeing_diameter_as, 
	plate_scale_as=1,
	padFactor=1,
	plotIt=False):
	"""
		 Convolve a Gaussian PSF with an input image to simulate seeing with a FWHM of seeing_diameter_as. 
	"""
	print("Seeing-limiting image(s)",end="")

	images, N, height, width = getImageSize(images)

	# Padding the source image.
	pad_ud = height // padFactor // 2
	pad_lr = width // padFactor // 2
	
	# If the image dimensions are odd, need to ad an extra row/column of zeros.
	image_padded = np.pad(images[0], ((pad_ud,pad_ud + height % 2),(pad_lr,pad_lr + width % 2)), mode='constant')
	# conv_height = image_padded.shape[0]
	# conv_width = image_padded.shape[1]
	conv_height = 2 * pad_ud + height + (height % 2)
	conv_width = 2 * pad_lr + width + (width % 2)

	# Generate a Gaussian kernel.
	kernel = np.zeros((conv_height, conv_width))
	y_as = np.arange(-conv_width//2, +conv_width//2 + conv_width%2, 1) * plate_scale_as
	x_as = np.arange(-conv_height//2, +conv_height//2 + conv_height%2, 1) * plate_scale_as
	X, Y = np.meshgrid(x_as, y_as)
	sigma = seeing_diameter_as / (2 * np.sqrt(2 * np.log(2)))
	kernel = np.exp(-(np.power(X, 2) + np.power(Y, 2)) / (2 * np.power(sigma,2)))
	kernel /= sum(kernel.flatten())
	kernel = np.pad(kernel, ((pad_ud, pad_ud + height % 2), (pad_lr, pad_lr + width % 2)), mode='constant')

	# Convolving the kernel with the image.
	image_seeing_limited = np.ndarray((N, conv_height, conv_width))
	image_seeing_limited_cropped = np.ndarray((N, height, width))

	for k in range(N):
		print('.',end="")
		image_padded = np.pad(images[k], ((pad_ud,pad_ud + height % 2),(pad_lr,pad_lr + width % 2)), mode='constant')
		image_seeing_limited[k] = signal.fftconvolve(image_padded, kernel, mode='same')
		image_seeing_limited_cropped[k] = image_seeing_limited[k,pad_ud : height + pad_ud, pad_lr : width + pad_lr]		

	if plotIt:
		mu.newfigure(2,2)
		plt.suptitle('Seeing-limiting image')
		plt.subplot(2,2,1)
		plt.imshow(images[0])
		mu.colourbar()
		plt.title('Input image')
		plt.subplot(2,2,2)
		plt.imshow(kernel, extent=axes_kernel)
		mu.colourbar()
		plt.title('Kernel')
		plt.subplot(2,2,3)
		plt.imshow(image_seeing_limited[0])
		mu.colourbar()
		plt.title('Convolved image')
		plt.subplot(2,2,4)
		plt.imshow(image_seeing_limited_cropped[0])
		mu.colourbar()
		plt.title('Cropped, convolved image')
		plt.show()

	return np.squeeze(image_seeing_limited_cropped)

####################################################################################################
def convolvePSF(image, psf, 
	padFactor=1,
	plotIt=False):
	"""
		 Convolve an input PSF with an input image. 
	"""

	# Padding the source image.
	height = image.shape[0]
	width = image.shape[1]
	pad_ud = height // padFactor // 2
	pad_lr = width // padFactor // 2
	
	# If the image dimensions are odd, need to ad an extra row/column of zeros.
	image_padded = np.pad(image, ((pad_ud,pad_ud + height % 2),(pad_lr,pad_lr + width % 2)), mode='constant')
	conv_height = 2 * pad_ud + height + (height % 2)
	conv_width = 2 * pad_lr + width + (width % 2)

	# Convolving the kernel with the image.
	image_conv = np.ndarray((conv_height, conv_width))
	image_conv_cropped = np.ndarray((height, width))

	image_padded = np.pad(image, ((pad_ud,pad_ud + height % 2),(pad_lr,pad_lr + width % 2)), mode='constant')
	image_conv = signal.fftconvolve(image_padded, psf, mode='same')
	image_conv_cropped = image_conv[pad_ud : height + pad_ud, pad_lr : width + pad_lr]		

	if plotIt:
		mu.newfigure(2,2)
		plt.suptitle('Seeing-limiting image')
		plt.subplot(2,2,1)
		plt.imshow(image)
		mu.colourbar()
		plt.title('Input image')
		plt.subplot(2,2,2)
		plt.imshow(psf)
		mu.colourbar()
		plt.title('Kernel')
		plt.subplot(2,2,3)
		plt.imshow(image_conv)
		mu.colourbar()
		plt.title('Convolved image (padded)')
		plt.subplot(2,2,4)
		plt.imshow(image_conv_cropped)
		mu.colourbar()
		plt.title('Convolved image (original size)')
		plt.show()

	return image_conv_cropped


####################################################################################################
def addNoise(images,
	noise_frames=None, 
	band=None,
	t_exp=None,
	etc_input=None,
	worstCaseSpider=False,
	plotIt=False):
	""" Add noise to an array of input images assuming an exposure time t_exp. """
	print ('Adding noise to image(s)...')

	# Creating an array in which to store the noisy images
	images, N, height, width = getImageSize(images)

	images_noisy = np.copy(images)

	# Determine whether or not we need to generate new noise frames
	if plt.is_numlike(noise_frames):
		generate_new_noise_frames = False
	else:
		noise_frames = np.zeros(images_noisy.shape)
		generate_new_noise_frames = True

	# Getting noise parameters from the ETC.
	if not etc_input and generate_new_noise_frames:
		if plt.is_numlike(t_exp) and band:
			etc_output = exposureTimeCalc(band = band,t_exp = t_exp, worstCaseSpider = worstCaseSpider)
		else:
			print("ERROR: if no ETC input is specified, then to calculate the noise levels you must also specify t_exp and the imaging band!")
			raise UserWarning
	else:
		etc_output = etc_input

	# Adding noise to each image.
	for k in range(N):
		if generate_new_noise_frames:
			frame_sky = np.random.poisson(lam=etc_output['N_sky'], size=(height, width))
			frame_dark = np.random.poisson(lam=etc_output['N_dark'], size=(height, width))
			frame_cryo = np.random.poisson(lam=etc_output['N_cryo'], size=(height, width))
			frame_RN = np.random.poisson(lam=etc_output['N_RN'], size=(height, width))
			noise_frames[k] = frame_sky + frame_cryo + frame_RN + frame_dark
		images_noisy[k] += noise_frames[k].astype(int)
	print('\n')

	if plotIt:
		mu.newfigure(1,2)
		plt.suptitle('Adding noise')
		plt.subplot(1,2,1)
		plt.imshow(images[0], vmin=min(images[0].flatten()), vmax=max(images_noisy[0].flatten()))
		mu.colourbar()
		plt.title('Raw input image')
		plt.subplot(1,2,2)
		plt.imshow(images_noisy[0], vmin=min(images[0].flatten()), vmax=max(images_noisy[0].flatten()))
		mu.colourbar()
		plt.title('Noisy image')
		plt.show()

	return (np.squeeze(images_noisy), np.squeeze(noise_frames), etc_output)

##########################################################################################
def strehl(psf, psf_dl):
	""" Calculate the Strehl ratio of an aberrated input PSF given the diffraction-limited PSF. """
	return np.amax(psf) / np.amax(psf_dl)
