"""Canonical NumPy/SciPy numerical operations owned by the tools.

Each entry is a real, correct implementation (not a stub, not model output),
keyed by operation name with aliases. ``generate_numerical_code`` looks an
operation up here; an unknown request returns the list of what is available.
"""
from __future__ import annotations

from typing import Dict, List, Optional

OPERATIONS: Dict[str, dict] = {
    "mean": {"aliases": ["average"], "library": "numpy",
             "code": "import numpy as np\n\ndef compute_mean(data):\n    \"\"\"Arithmetic mean of an array.\"\"\"\n    return float(np.mean(np.asarray(data, dtype=float)))\n"},
    "std": {"aliases": ["standard deviation", "stddev"], "library": "numpy",
            "code": "import numpy as np\n\ndef compute_std(data, ddof=0):\n    \"\"\"Standard deviation (ddof=0 population, 1 sample).\"\"\"\n    return float(np.std(np.asarray(data, dtype=float), ddof=ddof))\n"},
    "median": {"aliases": [], "library": "numpy",
               "code": "import numpy as np\n\ndef compute_median(data):\n    \"\"\"Median of an array.\"\"\"\n    return float(np.median(np.asarray(data, dtype=float)))\n"},
    "variance": {"aliases": ["var"], "library": "numpy",
                 "code": "import numpy as np\n\ndef compute_variance(data, ddof=0):\n    \"\"\"Variance (ddof=0 population, 1 sample).\"\"\"\n    return float(np.var(np.asarray(data, dtype=float), ddof=ddof))\n"},
    "normalize": {"aliases": ["min max scale", "minmax"], "library": "numpy",
                  "code": "import numpy as np\n\ndef normalize(data):\n    \"\"\"Min-max normalize an array to [0, 1].\"\"\"\n    a = np.asarray(data, dtype=float)\n    lo, hi = a.min(), a.max()\n    if hi == lo:\n        return np.zeros_like(a)\n    return (a - lo) / (hi - lo)\n"},
    "dot_product": {"aliases": ["dot", "inner product"], "library": "numpy",
                    "code": "import numpy as np\n\ndef dot_product(a, b):\n    \"\"\"Dot product of two vectors.\"\"\"\n    return float(np.dot(np.asarray(a, dtype=float), np.asarray(b, dtype=float)))\n"},
    "matrix_multiply": {"aliases": ["matmul", "matrix product"], "library": "numpy",
                        "code": "import numpy as np\n\ndef matrix_multiply(a, b):\n    \"\"\"Matrix product A @ B.\"\"\"\n    return np.asarray(a, dtype=float) @ np.asarray(b, dtype=float)\n"},
    "transpose": {"aliases": [], "library": "numpy",
                  "code": "import numpy as np\n\ndef transpose(matrix):\n    \"\"\"Transpose of a matrix.\"\"\"\n    return np.asarray(matrix, dtype=float).T\n"},
    "inverse": {"aliases": ["matrix inverse", "invert"], "library": "numpy",
                "code": "import numpy as np\n\ndef inverse(matrix):\n    \"\"\"Inverse of a square matrix.\"\"\"\n    return np.linalg.inv(np.asarray(matrix, dtype=float))\n"},
    "determinant": {"aliases": ["det"], "library": "numpy",
                    "code": "import numpy as np\n\ndef determinant(matrix):\n    \"\"\"Determinant of a square matrix.\"\"\"\n    return float(np.linalg.det(np.asarray(matrix, dtype=float)))\n"},
    "eigenvalues": {"aliases": ["eigen", "eig"], "library": "numpy",
                    "code": "import numpy as np\n\ndef eigenvalues(matrix):\n    \"\"\"Eigenvalues of a square matrix.\"\"\"\n    return np.linalg.eigvals(np.asarray(matrix, dtype=float))\n"},
    "solve_linear": {"aliases": ["solve linear system", "linear solve", "ax=b"], "library": "numpy",
                     "code": "import numpy as np\n\ndef solve_linear(A, b):\n    \"\"\"Solve the linear system A x = b.\"\"\"\n    return np.linalg.solve(np.asarray(A, dtype=float), np.asarray(b, dtype=float))\n"},
    "least_squares": {"aliases": ["lstsq", "linear regression"], "library": "numpy",
                      "code": "import numpy as np\n\ndef least_squares(A, b):\n    \"\"\"Least-squares solution to A x = b. Returns the coefficient vector.\"\"\"\n    solution, *_ = np.linalg.lstsq(np.asarray(A, dtype=float), np.asarray(b, dtype=float), rcond=None)\n    return solution\n"},
    "polyfit": {"aliases": ["polynomial fit", "curve fit"], "library": "numpy",
                "code": "import numpy as np\n\ndef polyfit(x, y, degree=1):\n    \"\"\"Fit a polynomial of the given degree; returns coefficients (highest power first).\"\"\"\n    return np.polyfit(np.asarray(x, dtype=float), np.asarray(y, dtype=float), degree)\n"},
    "fft": {"aliases": ["fourier transform", "fast fourier transform"], "library": "numpy",
            "code": "import numpy as np\n\ndef fft(signal):\n    \"\"\"Discrete Fourier transform of a 1-D signal.\"\"\"\n    return np.fft.fft(np.asarray(signal, dtype=float))\n"},
    "correlation": {"aliases": ["correlate", "pearson"], "library": "numpy",
                    "code": "import numpy as np\n\ndef correlation(a, b):\n    \"\"\"Pearson correlation coefficient between two arrays.\"\"\"\n    return float(np.corrcoef(np.asarray(a, dtype=float), np.asarray(b, dtype=float))[0, 1])\n"},
    "integrate": {"aliases": ["numerical integration", "quad", "definite integral"], "library": "scipy",
                  "code": "from scipy import integrate\n\ndef integrate_function(func, lower, upper):\n    \"\"\"Definite integral of func from lower to upper (SciPy quad).\"\"\"\n    value, _error = integrate.quad(func, lower, upper)\n    return value\n"},
    "interpolate": {"aliases": ["interpolation", "interp1d"], "library": "scipy",
                    "code": "from scipy import interpolate\n\ndef interpolate_1d(x, y, kind='linear'):\n    \"\"\"Return a callable interpolating (x, y).\"\"\"\n    return interpolate.interp1d(x, y, kind=kind)\n"},
}


def _norm(name: str) -> str:
    cleaned = name.lower().strip().replace("_", " ")
    return "".join(ch for ch in cleaned if ch.isalnum() or ch == " ").strip()


def lookup(name: str) -> Optional[dict]:
    key = _norm(name)
    compact = key.replace(" ", "_")
    for canonical, entry in OPERATIONS.items():
        if compact == canonical or key == canonical.replace("_", " "):
            return {"name": canonical, **entry}
        for alias in entry.get("aliases", []):
            if key == _norm(alias) or compact == _norm(alias).replace(" ", "_"):
                return {"name": canonical, **entry}
    # substring fall-through: a description that contains an operation name.
    for canonical, entry in OPERATIONS.items():
        candidates = [canonical.replace("_", " ")] + entry.get("aliases", [])
        if any(_norm(c) and _norm(c) in key for c in candidates):
            return {"name": canonical, **entry}
    return None


def available() -> List[str]:
    return sorted(OPERATIONS)
