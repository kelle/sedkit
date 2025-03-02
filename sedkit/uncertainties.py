"""
Module to calculate uncertainties
"""
from multiprocessing.pool import ThreadPool

import astropy.units as q
from bokeh.plotting import show, figure
import numpy as np
from scipy.integrate import quad
from scipy.optimize import leastsq

from .utilities import equivalent


def error_sample(nominal, upper, lower, n, units, low_lim=None, up_lim=None):
    """
    Function made to sample points given the 0.16, 0.5 and 0.84 quantiles of a parameter
    In the case of unequal variances, this algorithm assumes a skew-normal distribution and samples from it.
    If the variances are equal, it samples from a normal distribution.

    Parameters
    ----------
    nominal: int, float, astropy.units.quantity.Quantity
        The nominal value to sample around
    upper: int, float, astropy.units.quantity.Quantity
        The upper error
    lower: int, float, astropy.units.quantity.Quantity
        The lower error
    low_lim: float (optional)
        Lower limits on the values of the samples
    up_lim: float (optional)
        Upper limits on the values of the samples

    Returns
    -------
    The output are n samples from the distribution that best-matches the quantiles.
    *The optional inputs (low_lim and up_lim) are lower and upper limits that the samples have to have; if any of the samples
    surpasses those limits, new samples are drawn until no samples do. Note that this changes the actual variances of the samples.
    """
    if (upper != lower):

        # If errors are assymetric, sample from a skew-normal distribution given the location parameter (assumed to be the median), self.upper and self.lower.

        # First, find the parameters mu, sigma and alpha of the skew-normal distribution that
        # best matches the observed quantiles:
        sknorm = SkewNormal()
        sknorm.fit(nominal, upper, lower)

        # And now sample n values from the distribution:
        samples = sknorm.sample(n)

        # If a lower limit or an upper limit is given, then search if any of the samples surpass
        # those limits, and sample again until no sample surpasses those limits:
        if low_lim is not None:
            while True:
                idx = np.where(samples < low_lim)[0]
                l_idx = len(idx)
                if l_idx > 0:
                    samples[idx] = sknorm.sample(l_idx)
                else:
                    break

        if up_lim is not None:
            while True:
                idx = np.where(samples > up_lim)[0]
                l_idx = len(idx)
                if l_idx > 0:
                    samples[idx] = sknorm.sample(l_idx)
                else:
                    break

    else:

        # If errors are symmetric, sample from a gaussian
        samples = np.random.normal(nominal, upper, n)

        # If a lower limit or an upper limit is given, then search if any of the samples surpass
        # those limits, and sample again until no sample surpasses those limits:
        if low_lim is not None:
            while True:
                idx = np.where(samples < low_lim)[0]
                l_idx = len(idx)
                if l_idx > 0:
                    samples[idx] = np.random.normal(nominal, upper, l_idx)
                else:
                    break

        if up_lim is not None:
            while True:
                idx = np.where(samples > up_lim)[0]
                l_idx = len(idx)
                if l_idx > 0:
                    samples[idx] = np.random.normal(nominal, upper, l_idx)
                else:
                    break

    return samples * (units or 1)


class Unum:
    """
    An object to handle math with uncertainties
    """
    def __init__(self, nominal, upper, lower=None, n_samples=10000, sig_figs=2, method='median'):
        """
        Initialize a number with uncertainties
        """
        # Store values
        self.nominal = nominal
        self._nominal = nominal.value if hasattr(nominal, 'unit') else nominal
        self.upper = upper
        self._upper = upper.value if hasattr(upper, 'unit') else upper
        self.lower = lower or self.upper
        self._lower = lower.value if hasattr(lower, 'unit') else lower or self._upper
        self.units = nominal.unit if hasattr(nominal, 'unit') else None
        self.n = n_samples
        self.sig_figs = sig_figs
        self.method = method

    def __repr__(self):
        """
        repr method
        """
        if self.upper == self.lower:
            return '{}({}){}'.format(*self.value[:2], self.units or '')
        else:
            return '{}(+{},-{}){}'.format(*self.value, self.units or '')

    def __add__(self, other):
        """
        Add two numbers

        Parameters
        ----------
        other: int, float, Unum
            The number to add

        Returns
        -------
        Unum
            The Unum value
        """
        # Determine other units
        units = other.unit if hasattr(other, 'unit') else other.units if hasattr(other, 'units') else None

        # Validate units
        if not equivalent(self.units, units):
            raise TypeError("Cannot add values with units {} and {}".format(self.units, units or 'Unitless'))

        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, Unum) else other

        # Do math
        dist3 = dist1 + dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return Unum(*self.get_quantiles(dist3))

    def __mul__(self, other):
        """
        Multiply two numbers

        Parameters
        ----------
        other: int, float, Unum
            The number to multiply

        Returns
        -------
        Unum
            The Unum value
        """
        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, Unum) else other

        # Do math
        dist3 = dist1 * dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return Unum(*self.get_quantiles(dist3))

    def __sub__(self, other):
        """
        Subtract two numbers

        Parameters
        ----------
        other: int, float, Unum
            The number to subtract

        Returns
        -------
        Unum
            The Unum value
        """
        # Determine other units
        units = other.unit if hasattr(other, 'unit') else other.units if hasattr(other, 'units') else None

        # Validate units
        if not equivalent(self.units, units):
            raise TypeError("Cannot subtract values with units {} and {}".format(self.units, units or 'Unitless'))

        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, Unum) else other

        # Do math
        dist3 = dist1 - dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return Unum(*self.get_quantiles(dist3))

    def __pow__(self, exp):
        """
        Divide two numbers

        Parameters
        ----------
        exp: int, float
            The power to raise

        Returns
        -------
        Unum
            The Unum value
        """
        # Generate distributions for each number
        dist1 = self.sample_from_errors()

        # Do math
        dist3 = np.power(dist1, exp)

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return Unum(*self.get_quantiles(dist3))

    def __truediv__(self, other):
        """
        Divide the number by another

        Parameters
        ----------
        other: int, float, Unum
            The number to divide by

        Returns
        -------
        Unum
            The Unum value
        """
        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, Unum) else other

        # Do math
        dist3 = dist1 / dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return Unum(*self.get_quantiles(dist3))

    def __floordiv__(self, other):
        """
        Floor divide the number by another

        Parameters
        ----------
        other: int, float, Unum
            The number to floor divide by

        Returns
        -------
        Unum
            The Unum value
        """
        # Determine other units
        units = other.unit if hasattr(other, 'unit') else other.units if hasattr(other, 'units') else None

        # Validate units
        if not equivalent(self.units, units):
            raise TypeError("Cannot floordiv values with units {} and {}".format(self.units, units or 'Unitless'))

        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, Unum) else other

        # Do math
        dist3 = dist1 // dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return Unum(*self.get_quantiles(dist3))

    def get_quantiles(self, dist, alpha=0.68):
        """
        Determine the median, upper and lower quantiles of a distribution

        Parameters
        ----------
        dist: array-like
            The distribution to measure
        alpha: float
            The
        method: str
            The method used to determine the nominal value

        Returns
        -------
        tuple
            Median of the parameter, upper credibility bound, lower credibility bound
        """
        # Get units
        units = dist.unit if hasattr(dist, 'unit') and dist.unit != '' else 1
        dist = dist.value if hasattr(dist, 'unit') else dist

        # Order the distribution
        ordered_dist = dist[np.argsort(dist)]

        # Define the number of samples from posterior
        nsamples = len(dist)
        nsamples_at_each_side = int(nsamples * (alpha / 2.) + 1)

        if self.method == 'median':

            # Number of points is even
            if nsamples % 2 == 0.0:
                med_idx_upper = int(nsamples / 2.) + 1
                med_idx_lower = med_idx_upper - 1
                param = (ordered_dist[med_idx_upper] + ordered_dist[med_idx_lower]) / 2.

            else:
                med_idx_upper = med_idx_lower = int(nsamples / 2.)
                param = ordered_dist[med_idx_upper]

        q_upper = ordered_dist[med_idx_upper + nsamples_at_each_side]
        q_lower = ordered_dist[med_idx_lower - nsamples_at_each_side]

        return param.round(self.sig_figs) * units, (q_upper - param).round(self.sig_figs) * units, (param - q_lower).round(self.sig_figs) * units

    def log10(self):
        """
        Take the base 10 logarithm of the number

        Returns
        -------
        Unum
            The Unum value
        """
        # Generate distributions for each number
        dist1 = self.sample_from_errors()

        # Do math
        dist3 = np.log10(dist1)

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return Unum(*self.get_quantiles(dist3))

    def plot(self, bins=None):
        """
        Plot the distribution with stats

        Parameters
        ----------
        bins: int
            The number of bins for the histogram

        Returns
        -------
        bokeh.plotting.figure.Figure
        """
        # Make the figure
        fig = figure()

        # Make a histogram of the distribution
        dist = self.sample_from_errors()
        hist, edges = np.histogram(dist, density=True, bins=bins or min(self.n, 50))
        fig.quad(top=hist, bottom=0, left=edges[:-1], right=edges[1:], color='wheat')

        # Add stats to plot
        lower, nominal, upper = self.quantiles
        fig.line([lower] * 2, [min(hist), max(hist)], line_width=2, color='red', legend_label='lower (-{})'.format(self.lower))
        fig.line([nominal] * 2, [min(hist), max(hist)], line_width=2, color='black', legend_label='{} ({})'.format(self.method, self.nominal))
        fig.line([upper] * 2, [min(hist), max(hist)], line_width=2, color='blue', legend_label='upper (+{})'.format(self.upper))

        # Show the plot
        show(fig)

    def polyval(self, coeffs):
        """
        Evaluate the number in a polynomial

        Parameters
        ----------
        coeffs: list
            The polynomial coefficients in descending order

        Returns
        -------
        Unum
            The Unum value
        """
        # Generate distributions for each number
        dist1 = self.sample_from_errors()

        # Get units
        dist1 = dist1.value if hasattr(dist1, 'unit') else dist1

        # Do math
        dist3 = np.polyval(coeffs, dist1)

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return Unum(*self.get_quantiles(dist3))

    @property
    def quantiles(self):
        """
        The [0.15866, 0.5, 0.84134] quantiles
        """
        return self._nominal - self._lower, self._nominal, self._nominal + self._upper

    @property
    def quantity(self):
        """
        The nominal, upper, and lower quantities
        """
        return self.nominal, self.upper, self.lower

    def sample_from_errors(self, **kwargs):
        """
        A wrapper for the error_sample function

        Returns
        -------
        The output are n samples from the distribution that best-matches the quantiles.
        *The optional inputs (low_lim and up_lim) are lower and upper limits that the samples have to have; if any of the samples
        surpasses those limits, new samples are drawn until no samples do. Note that this changes the actual variances of the samples.
        """
        # Run error_sample function
        return error_sample(self._nominal, self._upper, self._lower, self.n, self.units, **kwargs)

    def to(self, units):
        """
        Convert Unum quantity to new units

        Parameters
        ----------
        units: astropy.units.quantity.Quantity
            The new units

        Returns
        -------
        Unum
            The Unum with new units
        """
        # Validate units
        if not equivalent(self.units, units):
            raise TypeError("Cannot convert units {} to {}".format(self.units, units))

        # Update values
        return Unum(self.nominal.to(units), self.upper.to(units), self.lower.to(units))

    @property
    def value(self):
        """
        The nominal, upper, and lower values
        """
        return self._nominal, self._upper, self._lower


class UArray:
    """
    An object to handle vectorized math with uncertainties
    """
    def __init__(self, nominal, upper, lower=None, n_samples=10000, sig_figs=2, method='median'):
        """
        Initialize a number with uncertainties
        """
        # Validate shapes
        if upper.shape != nominal.shape:
            raise ValueError("{} != {}: Nominal values and upper uncertainties must be the same shape.".format(nominal.shape, upper.shape))

        if lower is not None:
            if lower.shape != nominal.shape:
                raise ValueError("{} != {}: Nominal values and lower uncertainties must be the same shape.".format(nominal.shape, lower.shape))

        # Store values
        self.nominal = nominal
        self._nominal = nominal.value if hasattr(nominal, 'unit') else nominal
        self.upper = upper
        self._upper = upper.value if hasattr(upper, 'unit') else upper
        self.lower = self.upper if lower is None else lower
        self._lower = self._upper if lower is None else (lower.value if hasattr(lower, 'unit') else lower)
        self.units = nominal.unit if hasattr(nominal, 'unit') else None
        self.n = n_samples
        self.sig_figs = sig_figs
        self.method = method

    @property
    def shape(self):
        """Shape of the data"""
        return self._nominal.shape

    def __add__(self, other):
        """
        Add two numbers

        Parameters
        ----------
        other: int, float, Unum
            The number to add

        Returns
        -------
        Unum
            The Unum value
        """
        # Validate shape
        self._validate_shape(other)

        # Ensure same number of samples
        if isinstance(other, (Unum, UArray)):
            other.n = self.n

        # Determine other units
        units = other.unit if hasattr(other, 'unit') else other.units if hasattr(other, 'units') else None

        # Validate units
        if not equivalent(self.units, units):
            raise TypeError("Cannot add values with units {} and {}".format(self.units, units or 'Unitless'))

        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, (Unum, UArray)) else other

        # Massage dist2
        dist2 = self._prep_dist(dist1, dist2)

        # Do math
        dist3 = dist1 + dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return UArray(*self.get_quantiles(dist3))

    def _prep_dist(self, dist1, dist2):
        """
        Make sure dist2 has the same shape as dist 1

        Parameters
        ----------
        dist1: sequence
            The first distribution
        dist2: sequence
            The second distribution

        Returns
        -------
        dist2
            The corrected distribution
        """
        if isinstance(dist2, VALID_SHAPES):
            if hasattr(dist2, 'unit'):
                dist2, dunits = dist2.value, dist2.unit
            else:
                dunits = 1
            dist2 = np.asarray([dist2]).squeeze() * dunits

        if dist2.ndim == 1:
            dist2 = dist2[:, None]
            if dist2.shape[0] == dist1.shape[1]:
                dist2 = dist2.swapaxes(0, 1)

        return dist2

    def __mul__(self, other):
        """
        Multiply two numbers

        Parameters
        ----------
        other: int, float, Unum
            The number to multiply

        Returns
        -------
        Unum
            The Unum value
        """
        # Validate shape
        self._validate_shape(other)

        # Ensure same number of samples
        if isinstance(other, (Unum, UArray)):
            other.n = self.n

        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, (Unum, UArray)) else other

        # Massage dist2
        dist2 = self._prep_dist(dist1, dist2)

        # Do math
        dist3 = dist1 * dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return UArray(*self.get_quantiles(dist3))

    def __sub__(self, other):
        """
        Subtract two numbers

        Parameters
        ----------
        other: int, float, Unum
            The number to subtract

        Returns
        -------
        Unum
            The Unum value
        """
        # Validate shape
        self._validate_shape(other)

        # Ensure same number of samples
        if isinstance(other, (Unum, UArray)):
            other.n = self.n

        # Determine other units
        units = other.unit if hasattr(other, 'unit') else other.units if hasattr(other, 'units') else None

        # Validate units
        if not equivalent(self.units, units):
            raise TypeError("Cannot add values with units {} and {}".format(self.units, units or 'Unitless'))

        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, (Unum, UArray)) else other

        # Massage dist2
        dist2 = self._prep_dist(dist1, dist2)

        # Do math
        dist3 = dist1 - dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return UArray(*self.get_quantiles(dist3))

    def __pow__(self, exp):
        """
        Divide two numbers

        Parameters
        ----------
        exp: int, float
            The power to raise

        Returns
        -------
        Unum
            The Unum value
        """
        # Generate distributions for each number
        dist1 = self.sample_from_errors()

        # Do math
        dist3 = np.power(dist1, exp)

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return UArray(*self.get_quantiles(dist3))

    def __truediv__(self, other):
        """
        Divide the number by another

        Parameters
        ----------
        other: int, float, Unum
            The number to divide by

        Returns
        -------
        Unum
            The Unum value
        """
        # Validate shape
        self._validate_shape(other)

        # Ensure same number of samples
        if isinstance(other, (Unum, UArray)):
            other.n = self.n

        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, (Unum, UArray)) else other

        # Massage dist2
        dist2 = self._prep_dist(dist1, dist2)

        # Do math
        dist3 = dist1 / dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return UArray(*self.get_quantiles(dist3))

    def __floordiv__(self, other):
        """
        Floor divide the number by another

        Parameters
        ----------
        other: int, float, Unum
            The number to floor divide by

        Returns
        -------
        Unum
            The Unum value
        """
        # Validate shape
        self._validate_shape(other)

        # Ensure same number of samples
        if isinstance(other, (Unum, UArray)):
            other.n = self.n

        # Determine other units
        units = other.unit if hasattr(other, 'unit') else other.units if hasattr(other, 'units') else None

        # Validate units
        if not equivalent(self.units, units):
            raise TypeError("Cannot floordiv values with units {} and {}".format(self.units, units or 'Unitless'))

        # Generate distributions for each number
        dist1 = self.sample_from_errors()
        dist2 = other.sample_from_errors() if isinstance(other, (Unum, UArray)) else other

        # Massage dist2
        dist2 = self._prep_dist(dist1, dist2)

        # Do math
        dist3 = dist1 // dist2

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return UArray(*self.get_quantiles(dist3))

    def get_quantiles(self, dist, alpha=0.68):
        """
        Determine the median, upper and lower quantiles of a distribution

        Parameters
        ----------
        dist: array-like
            The distribution to measure
        alpha: float
            The
        method: str
            The method used to determine the nominal value

        Returns
        -------
        tuple
            Median of the parameter, upper credibility bound, lower credibility bound
        """
        # Get units
        units = dist.unit if hasattr(dist, 'unit') and dist.unit != '' else 1
        dist = dist.value if hasattr(dist, 'unit') else dist

        # Order the distribution
        ordered_dist = np.sort(dist, axis=1)

        # Define the number of samples from posterior
        nsamples = dist.shape[-1]
        nsamples_at_each_side = int(nsamples * (alpha / 2.) + 1)

        if self.method == 'median':

            # Number of points is even
            if nsamples % 2 == 0.0:
                med_idx_upper = int(nsamples / 2.) + 1
                med_idx_lower = med_idx_upper - 1
                param = (ordered_dist[:, med_idx_upper] + ordered_dist[:, med_idx_lower]) / 2.

            else:
                med_idx_upper = med_idx_lower = int(nsamples / 2.)
                param = ordered_dist[:, med_idx_upper]

        q_upper = ordered_dist[:, med_idx_upper + nsamples_at_each_side]
        q_lower = ordered_dist[:, med_idx_lower - nsamples_at_each_side]

        return param.round(self.sig_figs) * units, (q_upper - param).round(self.sig_figs) * units, (param - q_lower).round(self.sig_figs) * units

    def log10(self):
        """
        Take the base 10 logarithm of the number

        Returns
        -------
        Unum
            The Unum value
        """
        # Generate distributions for each number
        dist1 = self.sample_from_errors()

        # Do math
        dist3 = np.log10(dist1)

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return UArray(*self.get_quantiles(dist3))

    def plot(self):
        """
        Plot the arrays
        """
        # Get the date
        y_lower, y, y_upper = self.quantiles
        x = np.arange(len(y))

        # Make the figure
        fig = figure()
        fig.scatter(x, y)
        fig.yaxis.axis_label = 'Values {}'.format('' if self.units is None else '[{}]'.format(self.units))
        y_err_x = [(i, i) for i in x]
        y_err_y = [(yl, yu) for yl, yu in zip(y_lower, y_upper)]
        fig.multi_line(y_err_x, y_err_y)
        show(fig)

    def polyval(self, coeffs):
        """
        Evaluate the number in a polynomial

        Parameters
        ----------
        coeffs: list
            The polynomial coefficients in descending order

        Returns
        -------
        Unum
            The Unum value
        """
        # Generate distributions for each number
        dist1 = self.sample_from_errors()

        # Get units
        dist1 = dist1.value if hasattr(dist1, 'unit') else dist1

        # Do math
        dist3 = np.polyval(coeffs, dist1)

        # Make a new Unum from the new nominal value and upper and lower quantiles
        return UArray(*self.get_quantiles(dist3))

    @property
    def quantiles(self):
        """
        The [0.15866, 0.5, 0.84134] quantiles
        """
        return self._nominal - self._lower, self._nominal, self._nominal + self._upper

    @property
    def quantity(self):
        """
        The nominal, upper, and lower quantities
        """
        return self.nominal, self.upper, self.lower

    def sample_from_errors(self, **kwargs):
        """
        Vectorize the error_sample function

        Returns
        -------
        sequence
            The distributions for each array element
        """
        # Multiprocess distributions for each value in the array
        quantities = [(nom, up, low, self.n, self.units) for nom, up, low in zip(*self.value)]
        pool = ThreadPool(8)
        dists = np.asarray(pool.starmap(error_sample, quantities, **kwargs))
        pool.close()
        pool.join()
        del pool

        return np.asarray(dists) * (self.units or 1)

    def to(self, units):
        """
        Convert Unum quantity to new units

        Parameters
        ----------
        units: astropy.units.quantity.Quantity
            The new units

        Returns
        -------
        Unum
            The Unum with new units
        """
        # Validate units
        if not equivalent(self.units, units):
            raise TypeError("Cannot convert units {} to {}".format(self.units, units))

        # Update values
        return UArray(self.nominal.to(units), self.upper.to(units), self.lower.to(units))

    def _validate_shape(self, other):
        """
        Method to validate shape for math

        Parameters
        ----------
        other: sedkit.uncertainties.Unum, sedkit.uncertainties.UArray, int, float, astropy.units.quantity.Quantity
            The number(s) to evaluate
        """
        # Validate shape
        if isinstance(other, VALID_SHAPES):
            pass
        elif isinstance(other, (np.ndarray, UArray)):
            if other.shape != self.shape:
                raise ValueError("{} != {}: Value must be a number or array of the same shape.".format(self.shape, other.shape))
        else:
            raise ValueError("{}: Type not valid.".format(type(other)))

    @property
    def value(self):
        """
        The nominal, upper, and lower values
        """
        return self._nominal, self._upper, self._lower


class SkewNormal:
    """
    Description
    -----------
    This class defines a SkewNormal object, which generates a SkewNormal distribution given the quantiles
    from which you can then sample datapoints from.
    """
    def __init__(self):
        self.mu = 0.0
        self.sigma = 0.0
        self.alpha = 0.0

    def fit(self, median, sigma1, sigma2):
        """
        This function fits a Skew Normal distribution given
        the median, upper error bars (self.upper) and lower error bar (sigma2).
        """

        # First, define the sign of alpha, which should be positive if right skewed
        # and negative if left skewed:
        alpha_sign = np.sign(sigma1 - sigma2)

        # Now define the residuals of the least-squares problem:
        def residuals(p, data, x):
            mu, sqrt_sigma, sqrt_alpha = p
            return data - model(x, mu, sqrt_sigma, sqrt_alpha)

        # Define the model used in the residuals:
        def model(x, mu, sqrt_sigma, sqrt_alpha):
            """
            Note that we pass the square-root of the scale (sigma) and shape (alpha) parameters,
            in order to define the sign of the former to be positive and of the latter to be fixed given
            the values of self.upper and sigma2:
            """
            return self.cdf(x, mu, sqrt_sigma**2, alpha_sign * sqrt_alpha**2)

        # Define the quantiles:
        y = np.array([0.15866, 0.5, 0.84134])

        # Define the values at which we observe the quantiles:
        x = np.array([median - sigma2, median, median + sigma1])

        # Start assuming that mu = median, sigma = mean of the observed sigmas, and alpha = 0 (i.e., start from a gaussian):
        guess = (median, np.sqrt( 0.5 * (sigma1 + sigma2)), 0)

        # Perform the non-linear least-squares optimization:
        plsq = leastsq(residuals, guess, args=(y, x))[0]

        self.mu, self.sigma, self.alpha = plsq[0], plsq[1]**2, alpha_sign * plsq[2]**2

    def sample(self, n):
        """
        This function samples n points from a skew normal distribution using the
        method outlined by Azzalini here: http://azzalini.stat.unipd.it/SN/faq-r.html.
        """
        # Define delta:
        delta = self.alpha / np.sqrt(1 + self.alpha**2)

        # Now sample u0,u1 having marginal distribution ~N(0,1) with correlation delta:
        u0 = np.random.normal(0, 1, n)
        v = np.random.normal(0, 1, n)
        u1 = delta * u0 + np.sqrt(1 - delta**2) * v

        # Now, u1 will be random numbers sampled from skew-normal if the corresponding values
        # for which u0 are shifted in sign. To do this, we check the values for which u0 is negative:
        idx_negative = np.where(u0 < 0)[0]
        u1[idx_negative] = -u1[idx_negative]

        # Finally, we change the location and scale of the generated random-numbers and return the samples:
        return self.mu + self.sigma * u1

    @staticmethod
    def cdf(x, mu, sigma, alpha):
        """
        This function simply calculates the CDF at x given the parameters
        mu, sigma and alpha of a Skew-Normal distribution. It takes values or
        arrays as inputs.
        """
        if type(x) is np.ndarray:
           out = np.zeros(len(x))
           for i in range(len(x)):
               out[i] = quad(lambda x: SkewNormal.pdf(x, mu, sigma, alpha), -np.inf, x[i])[0]
           return out

        else:
           return quad(lambda x: SkewNormal.pdf(x, mu, sigma, alpha), -np.inf, x)[0]

    @staticmethod
    def pdf(x, mu, sigma, alpha):
        """
        This function returns the value of the Skew Normal PDF at x, given
        mu, sigma and alpha
        """
        def erf(x):
            # save the sign of x
            sign = np.sign(x)
            x = abs(x)

            # constants
            a1 = 0.254829592
            a2 = -0.284496736
            a3 = 1.421413741
            a4 = -1.453152027
            a5 = 1.061405429
            p = 0.3275911

            # A&S formula 7.1.26
            t = 1.0/(1.0 + p * x)
            y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * np.exp(-x * x)

            return sign * y

        def palpha(y, alpha):
            phi = np.exp(-y**2. / 2.0) / np.sqrt(2.0 * np.pi)
            PHI = (erf(y * alpha / np.sqrt(2)) + 1.0) * 0.5
            return 2 * phi * PHI

        return palpha((x - mu) / sigma, alpha) * (1. / sigma)


VALID_SHAPES = int, float, Unum, UArray, q.quantity.Quantity, q.core.PrefixUnit