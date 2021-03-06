################################################################################
#
# 	File:		skyclass.py
#	Author:		Anna Zovaro
#	Email:		anna.zovaro@anu.edu.au
#
#	Description:
#	A class for the sky.
#
#	Copyright (C) 2016 Anna Zovaro
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

################################################################################
class Sky(object):

	def __init__(self, T,
		eps=1.0,
		magnitude_system='AB',
		brightness=None
		):		
		
		# Sky brightness
		self.brightness = brightness
		
		# Magnitude scheme for the given brightnesses
		self.magnitude_system = magnitude_system

		# Temperature
		self.T = T 	# (kelvin)

		# Emissivity
		self.eps = eps
		



	