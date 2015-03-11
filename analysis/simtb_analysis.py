"""
Module for simtb analysis
"""

import matplotlib
matplotlib.use("Agg")

import argparse
import json
import logging
from matplotlib import pyplot as plt
from munkres import Munkres
import networkx as nx
import numpy as np
import os
from os import path
import pickle

from pl2mind.analysis import feature_extraction as fe
from pl2mind import logger
from pl2mind.tools import simtb_viewer
from pylearn2.datasets.transformer_dataset import TransformerDataset
from pylearn2.utils import serial


logger = logger.setup_custom_logger("pl2mind", logging.ERROR)

def save_simtb_montage(dataset, features, out_file, feature_dict,
                       target_stat=None, target_value=None):
    """
    Saves a simtb montage.
    """

    logger.info("Saving simtb montage")
    weights_view = dataset.get_weights_view(features)
    simtb_viewer.montage(weights_view, out_file=out_file,
                         feature_dict=feature_dict,
                         target_stat=target_stat,
                         target_value=target_value)

def save_simtb_spatial_maps(dataset, features, out_path):
    """
    Saves a series of simtb images.
    """
    logger.info("Saving simtb images")
    spatial_maps = features.spatial_maps
    spatial_maps = dataset.get_weights_view(spatial_maps)
    for i, feature in features.f.iteritems():
        spatial_map = spatial_maps[i]
        simtb_viewer.make_spatial_map_image(
            spatial_map, out_file=path.join(out_path, "%d.png" % feature.id))

def match_to_gt(p, gt, method="munkres", discard_misses=False):
    """
    Match parameter to ground truth features.
    """
    logger.info("Matching to ground truth")
    match_size = min(p.shape[0], gt.shape[0])
    corrs = np.corrcoef(p, gt)[match_size:,:match_size]
    corrs[np.isnan(corrs)] = 0

    if method == "munkres":
        m = Munkres()
        cl = 1 - np.abs(corrs)
        if (cl.shape[0] > cl.shape[1]):
            inds_r = m.compute(cl.T)
            indices = [(i[1], i[0]) for i in inds_r]
        else:
            indices = m.compute(cl)

    elif method == "greedy":
        gt_idx = []
        raise NotImplementedError()
        for c in range(self.gt.nC):
            idx = corrs[c, :].argmax()
            gt_idx.append(idx)
            corrs[:,idx] = 0

    else:
        raise NotImplementedError()

    return indices

def analyze_ground_truth(feature_dict, ground_truth_dict, dataset):
    """
    Compare models to ground truth.
    """
    gt_topo_view = ground_truth_dict[0]["SM"].reshape(
        (ground_truth_dict[0]["SM"].shape[0], ) +
        dataset.view_converter.shape).transpose(0, 2, 1, 3)
    gt_spatial_maps = dataset.get_design_matrix(gt_topo_view)
    gt_activations = ground_truth_dict[0]["TC"]

    for name, features in feature_dict.iteritems():
        logger.info("Analyzing %s compared to ground truth" % name)
        indices = match_to_gt(gt_spatial_maps, features.spatial_maps)
        for fi, gi in indices:
            features.f[fi].match_indices["ground_truth"] = gi

    feature_dict["ground_truth"] = fe.Features(gt_spatial_maps, gt_activations)

def main(model, out_path=None, prefix=None, **anal_args):
    """
    Main function of module.
    This function controls the high end analysis functions.

    Parameters
    ----------
    model: Pylearn2.Model or str
        Model instance or path for the model.
    out_path: str, optional
        Path for the output directory.
    prefix: str, optional
        If provided, prefix for all output files.
    dataset_root: str, optional
        If provided, use as the root dir for dataset extraction.
    anal_args: dict
        argparse arguments (defined below).
    """

    if out_path is None and prefix is None and isinstance(model, str):
        prefix = ".".join(path.basename(model).split(".")[:-1])
        sm_prefix = prefix
        nifti_prefix = prefix
    else:
        nifti_prefix = "image"

    if out_path is None:
        assert isinstance(model, str), ("If you provide a model object, you "
                                        "must provide an out_path")
        out_path = path.abspath(path.dirname(model))

    if isinstance(model, str):
        logger.info("Loading model from %s" % model)
        model = serial.load(model)

    if not path.isdir(out_path):
        os.mkdir(out_path)

    logger.info("Getting features")
    feature_dict = fe.extract_features(model, **anal_args)
    dataset = fe.resolve_dataset(model, **anal_args)
    if isinstance(dataset, TransformerDataset):
        dataset = dataset.raw

    ms = fe.ModelStructure(model, dataset)
    data_path = serial.preprocess(dataset.dataset_root + dataset.dataset_name)
    sim_dict_file = path.join(data_path, "sim_dict.pkl")
    sim_dict = pickle.load(open(sim_dict_file, "r"))
    analyze_ground_truth(feature_dict, sim_dict, dataset)

    anal_dict = dict()
    for name, features in feature_dict.iteritems():
        image_dir = path.join(out_path, "%s_images" % name)
        if not path.isdir(image_dir):
            os.mkdir(image_dir)
        save_simtb_spatial_maps(dataset, features, image_dir)

        features.set_histograms(tolist=True)
        fds = dict()
        for k, f in features.f.iteritems():
            fd = dict(
                image=path.join("%s_images" % name, "%d.png" % f.id),
                image_type="simtb",
                index=f.id,
                hists=f.hists,
                match_indices=f.match_indices
            )
            fd.update(**f.stats)

            fds[k] = fd

        anal_dict[name] = dict(
            name=name,
            image_dir=image_dir,
            features=fds
        )

    json_file = path.join(out_path, "analysis.json")
    with open(json_file, "w") as f:
        json.dump(anal_dict, f)

    logger.info("Done.")

def make_argument_parser():
    """
    Creates an ArgumentParser to read the options for this script from
    sys.argv
    """
    parser = argparse.ArgumentParser()

    parser.add_argument("model_path", help="Path for the model .pkl file.")

    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show more verbosity!")
    parser.add_argument("-o", "--out_dir", default=None,
                        help="output path for the analysis files.")
    parser.add_argument("-p", "--prefix", default=None,
                        help="Prefix for output files.")

    parser.add_argument("-z", "--zscore", action="store_true")
    parser.add_argument("-t", "--target_stat", default=None)
    parser.add_argument("-m", "--max_features", default=100)
    parser.add_argument("-d", "--dataset_root", default=None,
                        help="If specified, use another user's data root")
    return parser

if __name__ == "__main__":
    parser = make_argument_parser()
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    anal_args = dict(
        zscore=args.zscore,
        target_stat=args.target_stat,
        max_features=args.max_features,
        dataset_root=args.dataset_root,
    )

    main(args.model_path, args.out_dir, args.prefix, **anal_args)