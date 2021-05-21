# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# The Original Code is Copyright (C) 2021, TIALab, University of Warwick
# All rights reserved.
# ***** END GPL LICENSE BLOCK *****


import os
import pathlib

import numpy as np
import PIL
import torch
import torchvision.transforms as transforms

from tiatoolbox import rcParam
from tiatoolbox.utils.misc import download_data, grab_files_from_dir, imread, unzip_data


class _TorchPreprocCaller:
    """Wrapper for applying PyTorch transforms.

    Args:
        preproc_list (list): List of torchvision transforms for preprocessing the image.
            The transforms will be applied in the order that they are
            given in the list. https://pytorch.org/vision/stable/transforms.html.

    """

    def __init__(self, preproc_list):
        self.func = transforms.Compose(preproc_list)

    def __call__(self, img):
        img = PIL.Image.fromarray(img)
        img = self.func(img)
        img = img.permute(1, 2, 0)
        return img


def predefined_preproc_func(dataset_name):
    """Get the preprocessing information used for the pretrained model.

    Args:
        dataset_name (str): Dataset name used to determine what preprocessing was used.

    """
    preproc_dict = {
        "kather100k": [
            transforms.ToTensor(),
        ]
    }
    if dataset_name not in preproc_dict:
        raise ValueError(
            "Predefined preprocessing for" "dataset `%s` does not exist." % dataset_name
        )

    preproc_list = preproc_dict[dataset_name]
    preproc_func = _TorchPreprocCaller(preproc_list)
    return preproc_func


class __ABC_Dataset(torch.utils.data.Dataset):
    """Defines abstract base class for patch dataset.

    Attributes:
        return_labels (bool, False): `__getitem__` will return both the img and
        its label.
                If `label_list` is `None`, `None` is returned

        preproc_func: Preprocessing function used to transform the input data. If
        supplied, then torch.Compose will be used on the input preproc_list.
        preproc_list is a list of torchvision transforms for preprocessing the image.
        The transforms will be applied in the order that they are given in the list.
        https://pytorch.org/vision/stable/transforms.html.

    """

    def __init__(self, return_labels=False, preproc_func=None):
        super().__init__()
        self.set_preproc_func(preproc_func)
        self.data_is_npy_alike = False
        self.return_labels = return_labels
        self.img_list = None
        self.label_list = None

    @staticmethod
    def load_img(path):
        """Load an image from a provided path.

        Args:
            path (str): Path to an image file.

        """
        path = pathlib.Path(path)
        if path.suffix == ".npy":
            patch = np.load(path)
        elif path.suffix in (".jpg", ".jpeg", ".tif", ".tiff", ".png"):
            patch = imread(path)
        else:
            raise ValueError("Can not load data of `%s`" % path.suffix)
        return patch

    def set_preproc_func(self, func):
        """Set the `preproc_func` to this `func` if it is not None.
        Else the `preproc_func` is reset to return source image.

        `func` must behave in the following manner:

        >>> transformed_img = func(img)

        """
        self.preproc_func = func if func is not None else lambda x: x

    def __len__(self):
        return len(self.img_list)

    def __getitem__(self, idx):
        patch = self.img_list[idx]
        # Mode 0 is list of paths
        if not self.data_is_npy_alike:
            patch = self.load_img(patch)

        # Apply preprocessing to selected patch
        patch = self.preproc_func(patch)

        if self.return_labels:
            return patch, self.label_list[idx]

        return patch


class PatchDataset(__ABC_Dataset):
    """Defines a simple patch dataset, which inherits
    from the torch.utils.data.Dataset class.

    Attributes:
        img_list: Either a list of patches, where each patch is a ndarray or a list of
         valid path with its extension be (".jpg", ".jpeg", ".tif", ".tiff", ".png")
         pointing to an image.

        label_list: List of label for sample at the same index in `img_list` .
        Default is `None`.

        return_labels (bool, False): `__getitem__` will return both the img
        and its label. If `label_list` is `None`, `None` is returned

        preproc_func: Preprocessing function used to transform the input data. If
         supplied, then torch.Compose will be used on the input preproc_list.
         preproc_list is a list of torchvision transforms for preprocessing the image.
         The transforms will be applied in the order that they are given in the list.
         https://pytorch.org/vision/stable/transforms.html.

    Examples:
        >>> from tiatoolbox.models.data import Patch_Dataset
        >>> mean = [0.485, 0.456, 0.406]
        >>> std = [0.229, 0.224, 0.225]
        >>> preproc_list =
                [
                    transforms.Resize(224),
                    transforms.ToTensor(),
                    transforms.Normalize(mean=mean, std=std)
                ]
        >>> ds = Patch_Dataset('/path/to/data/', preproc_list=preproc_list)

    """

    def __init__(
        self, img_list, label_list=None, return_labels=False, preproc_func=None
    ):
        super().__init__(return_labels=return_labels, preproc_func=preproc_func)

        self.data_is_npy_alike = False

        # Perform check on the input
        # ? move to ABC ?

        # If input is a list - can contain a list of images or a list of image paths
        if isinstance(img_list, list):
            is_all_path_list = all(isinstance(v, (pathlib.Path, str)) for v in img_list)
            is_all_npy_list = all(isinstance(v, np.ndarray) for v in img_list)
            if not (is_all_path_list or is_all_npy_list):
                raise ValueError(
                    "Input must be either a list/array of images "
                    "or a list of valid image paths."
                )

            shape_list = []
            # When a list of paths is provided
            if is_all_path_list:
                if any(not os.path.exists(v) for v in img_list):
                    # at least one of the paths are invalid
                    raise ValueError(
                        "Input must be either a list/array of images "
                        "or a list of valid image paths."
                    )
                # Preload test for sanity check
                shape_list = [self.load_img(v).shape for v in img_list]
                self.data_is_npy_alike = False
            else:
                shape_list = [v.shape for v in img_list]
                self.data_is_npy_alike = True

            if any(len(v) != 3 for v in shape_list):
                raise ValueError("Each sample must be an array of the form HWC.")

            max_shape = np.max(shape_list, axis=0)
            # How will this behave for mixed channel ?
            if (shape_list - max_shape[None]).sum() != 0:
                raise ValueError("Images must have the same dimensions.")

        # If input is a numpy array
        elif isinstance(img_list, np.ndarray):
            # Check that input array is numerical
            if not np.issubdtype(img_list.dtype, np.number):
                # ndarray of mixed data types
                raise ValueError("Provided input array is non-numerical.")
            # N H W C | N C H W
            if len(img_list.shape) != 4:
                raise ValueError(
                    "Input must be an array of images of the form NHWC. This can "
                    "be achieved by converting a list of images to a numpy array. "
                    " eg., np.array([img1, img2])."
                )
            self.data_is_npy_alike = True

        else:
            raise ValueError(
                "Input must be either a list/array of images "
                "or a list of valid paths to image."
            )

        if label_list is None:
            label_list = [np.nan for i in range(len(img_list))]

        self.img_list = img_list
        self.label_list = label_list
        self.return_labels = return_labels


class KatherPatchDataset(__ABC_Dataset):
    """Define a dataset class specifically for the Kather dataset, obtain from [URL].

    Attributes:
        save_dir_path (str or None): Path to directory containing the Kather dataset,
                 assumed to be as is after extracted. If the argument is `None`,
                 the dataset will be downloaded and extracted into the
                 'run_dir/download/Kather'.

        preproc_list: List of preprocessing to be applied. If not provided, by default
                      the following are applied in sequential order.

    """

    def __init__(
        self,
        save_dir_path=None,
        return_labels=False,
        preproc_func=None,
    ):
        super().__init__(return_labels=return_labels, preproc_func=preproc_func)

        self.data_is_npy_alike = False

        label_code_list = [
            "01_TUMOR",
            "02_STROMA",
            "03_COMPLEX",
            "04_LYMPHO",
            "05_DEBRIS",
            "06_MUCOSA",
            "07_ADIPOSE",
            "08_EMPTY",
        ]

        if save_dir_path is None:
            save_dir_path = os.path.join(rcParam["TIATOOLBOX_HOME"], "dataset/")
            if not os.path.exists(save_dir_path):
                save_zip_path = os.path.join(save_dir_path, "Kather.zip")
                url = (
                    "https://zenodo.org/record/53169/files/"
                    "Kather_texture_2016_image_tiles_5000.zip"
                )
                download_data(url, save_zip_path)
                unzip_data(save_zip_path, save_dir_path)
            save_dir_path = os.path.join(
                save_dir_path, "Kather_texture_2016_image_tiles_5000/"
            )
        elif not os.path.exists(save_dir_path):
            raise ValueError("Dataset does not exist at `%s`" % save_dir_path)

        # What will happen if downloaded data get corrupted?
        all_path_list = []
        for label_id, label_code in enumerate(label_code_list):
            path_list = grab_files_from_dir(
                "%s/%s/" % (save_dir_path, label_code), file_types="*.tif"
            )
            path_list = [[v, label_id] for v in path_list]
            path_list.sort()
            all_path_list.extend(path_list)
        img_list, label_list = list(zip(*all_path_list))

        self.img_list = img_list
        self.label_list = label_list
        self.classes = label_code_list