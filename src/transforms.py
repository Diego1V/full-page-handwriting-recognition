import random
import math
from functools import partial
from dataclasses import dataclass, field
from typing import Tuple

import cv2 as cv
import albumentations as A
import numpy as np


def randomly_displace_and_pad(
    img: np.ndarray,
    padded_size: Tuple[int, int],
    crop_if_necessary: bool = False,
    **kwargs,
) -> np.ndarray:
    """
    Randomly displace an image within a frame, and pad zeros around the image.

    Args:
        img (np.ndarray): image to process
        padded_size (Tuple[int, int]): (height, width) tuple indicating the size of the frame
        crop_if_necessary (bool): whether to crop the image if its size exceeds that
            of the frame
    """
    frame_h, frame_w = padded_size
    img_h, img_w = img.shape
    if frame_h < img_h or frame_w < img_w:
        if crop_if_necessary:
            print(
                "WARNING (`randomly_displace_and_pad`): cropping input image before "
                "padding because it exceeds the size of the frame."
            )
            img_h, img_w = min(img_h, frame_h), min(img_w, frame_w)
            img = img[:img_h, :img_w]
        else:
            raise AssertionError(
                f"Frame is smaller than the image: ({frame_h}, {frame_w}) vs. ({img_h},"
                f" {img_w})"
            )

    res = np.zeros((frame_h, frame_w), dtype=img.dtype)

    pad_top = random.randint(0, frame_h - img_h)
    pad_bottom = pad_top + img_h
    pad_left = random.randint(0, frame_w - img_w)
    pad_right = pad_left + img_w

    res[pad_top:pad_bottom, pad_left:pad_right] = img
    return res


def dpi_adjusting(img: np.ndarray, scale: float, **kwargs) -> np.ndarray:
    height, width = img.shape[:2]
    new_height, new_width = math.ceil(height * scale), math.ceil(width * scale)
    return cv.resize(img, (new_width, new_height))


class SafeRandomScale(A.RandomScale):
    """Checks if the scaled image dimensions are valid before applying random scaling."""

    def apply(self, img, scale=0, interpolation=cv.INTER_LINEAR, **params):
        height, width = img.shape[:2]
        new_height, new_width = int(height * scale), int(width * scale)
        if new_height <= 0 or new_width <= 0:
            return img
        return super().apply(img, scale, interpolation, **params)


@dataclass
class IAMImageTransforms:
    """Image transforms for the IAM dataset.

    All images are padded to the same size. For form images, images are randomly
    displaced before padding during training, and centered during validation and
    testing.
    """

    max_img_size: Tuple[int, int]  # (h, w)
    parse_method: str
    normalize_params: Tuple[float, float]  # (mean, std)
    scale: float = (
        0.5  # assuming A4 paper, this gives ~140 DPI (see Singh et al. p. 8, section 4)
    )
    random_scale_limit: float = 0.1
    random_rotate_limit: int = 10
    train_trnsf: A.Compose = field(init=False)
    test_trnsf: A.Compose = field(init=False)

    def __post_init__(self):
        scale, random_scale_limit, random_rotate_limit, normalize_params = (
            self.scale,
            self.random_scale_limit,
            self.random_rotate_limit,
            self.normalize_params,
        )
        max_img_h, max_img_w = self.max_img_size

        max_scale = scale + scale * random_scale_limit

        padded_h, padded_w = math.ceil(max_scale * max_img_h), math.ceil(
            max_scale * max_img_w
        )

        if self.parse_method == "word":
            self.train_trnsf = A.Compose(
                [
                    A.Lambda(partial(dpi_adjusting, scale=scale)),
                    SafeRandomScale(scale_limit=random_scale_limit, p=0.5),
                    A.SafeRotate(
                        limit=random_rotate_limit,
                        border_mode=cv.BORDER_CONSTANT,
                        value=0,
                    ),
                    A.RandomBrightnessContrast(),
                    A.GaussNoise(),
                    A.Normalize(*normalize_params),
                ]
            )
            self.test_trnsf = A.Compose(
                [
                    A.Lambda(partial(dpi_adjusting, scale=scale)),
                    A.Normalize(*normalize_params),
                ]
            )
        elif self.parse_method == "line":
            self.train_trnsf = A.Compose(
                [
                    A.Lambda(partial(dpi_adjusting, scale=scale)),
                    SafeRandomScale(scale_limit=random_scale_limit, p=0.5),
                    A.SafeRotate(
                        limit=random_rotate_limit,
                        border_mode=cv.BORDER_CONSTANT,
                        value=0,
                    ),
                    A.RandomBrightnessContrast(),
                    A.GaussNoise(),
                    A.Normalize(*normalize_params),
                ]
            )
            self.test_trnsf = A.Compose(
                [
                    A.Lambda(partial(dpi_adjusting, scale=scale)),
                    A.Normalize(*normalize_params),
                ]
            )
        elif self.parse_method == "form":
            self.train_trnsf = A.Compose(
                [
                    A.Lambda(partial(dpi_adjusting, scale=scale)),
                    SafeRandomScale(scale_limit=random_scale_limit, p=0.5),
                    # SafeRotate is preferred over Rotate because it does not cut off
                    # text when it extends out of the frame after rotation.
                    A.SafeRotate(
                        limit=random_rotate_limit,
                        border_mode=cv.BORDER_CONSTANT,
                        value=0,
                    ),
                    A.RandomBrightnessContrast(),
                    A.Perspective(scale=(0.03, 0.05)),
                    A.GaussNoise(),
                    A.Normalize(*normalize_params),
                    A.Lambda(
                        image=partial(
                            randomly_displace_and_pad,
                            padded_size=(padded_h, padded_w),
                            crop_if_necessary=True,
                        )
                    ),
                ]
            )
            self.test_trnsf = A.Compose(
                [
                    A.Lambda(partial(dpi_adjusting, scale=scale)),
                    A.Normalize(*normalize_params),
                    A.PadIfNeeded(
                        max_img_h, max_img_w, border_mode=cv.BORDER_CONSTANT, value=0
                    ),
                ]
            )
        else:
            raise ValueError(f"{self.parse_method} is not a valid parse method.")
