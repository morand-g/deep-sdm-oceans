import os
from argparse import Namespace
from pathlib import Path

import hydra
from omegaconf import DictConfig
import numpy as np
import pytorch_lightning as pl
import torch
from pytorch_lightning.callbacks import ModelCheckpoint, ModelSummary
from torchvision import transforms

from malpolon.data.data_module import BaseDataModule
from malpolon.data.environmental_raster import PatchExtractor
from malpolon.data.datasets.geolifeclef import GeoLifeCLEF2022Dataset, MiniGeoLifeCLEF2022Dataset

from cnn_on_rgb_patches import ClassificationSystem


class ReplaceChannelsByBIOTEMPTransform:
    def __call__(self, data):
        mu = np.asarray([-12.0, 1.0, 1.0], dtype=np.float32)[:, None, None]
        sigma = np.asarray([40.0, 22.0, 51.0], dtype=np.float32)[:, None, None]
        data = (data - mu) / sigma
        data = torch.as_tensor(data, dtype=torch.float32)
        data = transforms.functional.resize(data, 256)
        return data


class GeoLifeCLEF2022DataModule(BaseDataModule):
    r"""
    Data module for GeoLifeCLEF 2022.

    Parameters
    ----------
        dataset_path: Path to dataset
        minigeolifeclef: if True, loads MiniGeoLifeCLEF 2022, otherwise loads GeoLifeCLEF2022
        train_batch_size: Size of batch for training
        inference_batch_size: Size of batch for inference (validation, testing, prediction)
        num_workers: Number of workers to use for data loading
    """
    def __init__(
        self,
        dataset_path: str,
        minigeolifeclef: bool = False,
        train_batch_size: int = 32,
        inference_batch_size: int = 256,
        num_workers: int = 8,
    ):
        super().__init__(train_batch_size, inference_batch_size, num_workers)
        self.dataset_path = dataset_path
        self.minigeolifeclef = minigeolifeclef

    @property
    def train_transform(self):
        return transforms.Compose(
            [
                ReplaceChannelsByBIOTEMPTransform(),
                transforms.RandomRotation(degrees=45, fill=255),
                transforms.RandomCrop(size=224),
                transforms.RandomHorizontalFlip(),
                transforms.RandomVerticalFlip(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
                ),
            ]
        )

    @property
    def test_transform(self):
        return transforms.Compose(
            [
                ReplaceChannelsByBIOTEMPTransform(),
                transforms.CenterCrop(size=224),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
                ),
            ]
        )

    def get_dataset(self, split, transform, **kwargs):
        if self.minigeolifeclef:
            dataset_cls = MiniGeoLifeCLEF2022Dataset
        else:
            dataset_cls = GeoLifeCLEF2022Dataset

        patch_extractor = PatchExtractor(Path(self.dataset_path) / "rasters", size=20)
        patch_extractor.append("bio_1", nan=-12.0)
        patch_extractor.append("bio_2", nan=1.0)
        patch_extractor.append("bio_7", nan=1.0)

        dataset = dataset_cls(
            self.dataset_path,
            split,
            patch_data=[],
            use_rasters=True,
            patch_extractor=patch_extractor,
            transform=transform,
            **kwargs
        )
        return dataset


@hydra.main(version_base="1.1", config_path=".", config_name="cnn_on_rgb_patches_config")
def main(cfg: DictConfig) -> None:
    logger = pl.loggers.CSVLogger(".", name=False, version="")
    logger.log_hyperparams(cfg)

    datamodule = GeoLifeCLEF2022DataModule.from_argparse_args(Namespace(**cfg.data))

    model = ClassificationSystem.from_argparse_args(Namespace(**cfg.model))

    callbacks = [
        ModelSummary(max_depth=3),
        ModelCheckpoint(
            dirpath=os.getcwd(),
            filename="checkpoint-{epoch:02d}-{step}-{val_top_k_accuracy:.4f}",
            monitor="val_top_k_accuracy",
            mode="max",
        ),
    ]
    trainer = pl.Trainer(logger=logger, callbacks=callbacks, **cfg.trainer)
    trainer.fit(model, datamodule=datamodule)

    trainer.test(model, datamodule=datamodule)


if __name__ == "__main__":
    main()
