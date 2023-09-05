# deepbiosphere packages
import deepbiosphere.Run as run
import deepbiosphere.Utils as utils
import deepbiosphere.Models as mods
from deepbiosphere.Utils import paths
import deepbiosphere.Dataset as dataset
import deepbiosphere.NAIP_Utils as naip
from deepbiosphere.Models import Model as mods
from deepbiosphere.Losses import Loss as losses

# ML + statistics packages
import torch
import argparse
import numpy as np
import pandas as pd
import sklearn.metrics as mets
from torch.utils.data import DataLoader

# miscellaneous packages
import os
import csv
import glob
import time
import json
import warnings
from tqdm import tqdm
from datetime import date
from os.path import exists


def load_baseline_preds(model, nobs, nspecs, sp2id, band='unif_train_test', dset_name='big_cali_2012'):
    files = glob.glob(f"{paths.BASELINES}{model}/predictions/{dset_name}/{band}/*csv")
    results = np.zeros((nobs, nspecs))
    for file in tqdm(files):
        pred = pd.read_csv(file)
        spec = file.split('/')[-1].split(f'_{model}_preds.csv')[0].replace('_', ' ')
        if model == 'maxent':            
            # fill in predictions to be in same order as CNN model
            results[:,sp2id[spec]] = pred.pres_pred
        elif model == 'rf':
            results[:,sp2id[spec]] = pred.presence
        else:
            # TODO: figure out biomod probs
            raise NotImplemented
    
    # for locations with NaNs, impute
    # a probability of 0 at those locations
    # (only really relevant for baseline models)
    # because some sklearn functions will
    # handle the Nan
    if np.isnan(results).sum() > 0:
        results = np.ma.MaskedArray(results, np.isnan(results))
        results = results.filled(fill_value=0.0)

    return results

def write_overall_metric(dict_, sc, scorename, thres, weight):
    dict_['value'] = sc
    dict_['metric'] = scorename
    dict_['weight'] = weight
    dict_['thres'] = thres
    return dict_

def write_topk_metric(dict_, single_ytrue, preds, K, topKmet, type_):
    dict_['metric'] = f"{type_}_top{K}"
    dict_['weight'] = np.nan
    dict_['value'] =  topKmet(single_ytrue, preds, K)[0]
    return dict_

def write_spec_metric(dict_, metric, thres, vals, id2sp):
    dict_['metric'] = metric
    dict_['thres'] = thres
    re = {id2sp[i] : vals[i] for i in range(len(vals))}
    dict_.update(re)
    return dict_

def write_obs_metrics(dict_, metric, vals, ids, writer):
    dict_['metric'] = metric
    for v, id_ in zip(vals, ids):
        dict_['value'] = v.item()
        dict_['ID'] = id_
        writer.writerow(dict_)
        
def add_mean_stdev(vals, df, row, col):
    means = vals.mean(axis=0)
    stds = vals.std(axis=0)
    df.at[row,col] = f"{round(means, 4)}±{round(stds,4)}"
    
def add_med_iqr(vals, df, row, col):
    med = np.median(vals, axis=0)
    q75, q25 = np.percentile(vals, [75 ,25], axis=0)
    df.at[row,col] = f"{round(med, 4)} [{round(q25,4)}-{round(q75, 4)}]" 
            

def evaluate_model(ytrue, single_ytrue, preds_multi, preds_single, sharedspecs, sp2id, ids, dset_name, band, model, loss, lr, epoch, exp_id, pretrained, batch_size, write_obs=False, thres=0.5, filename=None):
    tick = time.time()
    
    # make directory if it doesn't exist
    if not os.path.exists(f"{paths.RESULTS}accuracy_metrics/"):
        os.makedirs(f"{paths.RESULTS}accuracy_metrics/")

    # save unique identifier for file if necessary
    filename = "" if filename is None else filename
    fname = f"{paths.RESULTS}accuracy_metrics/{filename}_overall_metrics_results_band{band}.csv"
    fexists = os.path.isfile(fname)
    overallcsv = open(fname, 'a')
    nmets = 46 if write_obs else 42
    prog = tqdm(total=nmets, unit="metric", desc='Accuracy metrics')
    basics = {
        'value' : np.nan,
        'dset_name' : dset_name,
        'band' : band,
        'model' : model,
        'loss' : loss,
        'lr' : lr,
        'epoch' : epoch,
        'exp_id' : exp_id,
        'pretrained' : pretrained, 
        'batch_size' : batch_size,
        'metric' : np.nan,
        'weight' : np.nan,
        'thres' : thres,
        'date' : date.today(),
    }
    overallwriter = csv.DictWriter(overallcsv, delimiter=',', lineterminator='\n',fieldnames=basics.keys())
    if not fexists:
        overallwriter.writeheader()  # file doesn't exist yet, write a header

    ## working zone below
    id2sp = {v:k for k, v in sp2id.items()}
    yobs = preds_multi >= thres
    
    
    # run + write overall binary accuracy metrics
    scores = [mets.precision_score, mets.recall_score, mets.f1_score, 
              mets.jaccard_score]
    for score in scores:
        averages = ['macro', 'micro', 'weighted', 'samples']
        for avg in averages:
            sc = score(ytrue, yobs, average=avg, zero_division=0.0)
            overallwriter.writerow(write_overall_metric(basics, sc, score.__name__, thres, avg))
            prog.update(1)
    # label ranking average precision
    macc = mets.label_ranking_average_precision_score(ytrue, preds_multi)
    overallwriter.writerow(write_overall_metric(basics, macc, 'label_ranking_average_precision_score', np.nan, np.nan))
    prog.update(1)
    # also get overall species 0/1 accuracy
    acc = utils.zero_one_accuracy(single_ytrue, preds_single, thres)
    overallwriter.writerow(write_overall_metric(basics, acc, 'zero_one_accuracy', thres, np.nan))
    prog.update(1)
    # run + write topK metrics 
    for i in [1,5,30,100]:
        overallwriter.writerow(write_topk_metric(basics, single_ytrue, preds_single, i, utils.obs_topK, 'obs'))
        prog.update(1)
        overallwriter.writerow(write_topk_metric(basics, single_ytrue, preds_single, i, utils.species_topK, 'species'))
        prog.update(1)
        # now, write out per-species metrics
    fname = f"{paths.RESULTS}accuracy_metrics/{filename}_per_species_metrics_results_band{band}.csv"
    fexists = os.path.isfile(fname)
    csvfile = open (fname, 'a')
    dict_ = { k: np.nan for k,v in sp2id.items()}
    dict_.update(basics)
    # don't use these columns for species dict
    del dict_['weight'], dict_['value']
    writer = csv.DictWriter(csvfile, delimiter=',', lineterminator='\n',fieldnames=dict_.keys())
    if not fexists:
        writer.writeheader()  # file doesn't exist yet, write a header

    # run + write out roc-auc, prc-auc
    assert len(preds_multi.shape) == 2, 'too many dimensions in probabilty vector!'
    aucs, prcs = [], []
    for i in range(preds_multi.shape[1]):
        try:
            aucs.append(mets.roc_auc_score(ytrue[:,i], preds_multi[:,i]))
            prcs.append(mets.average_precision_score(ytrue[:,i], preds_multi[:,i]))
        except:
            aucs.append(np.nan)
            prcs.append(np.nan)
    # also write out average AUCs
    aucmean = np.ma.MaskedArray(aucs, np.isnan(aucs)).mean()
    overallwriter.writerow(write_overall_metric(basics, aucmean, 'ROC_AUC', np.nan, np.nan))
    prcmean = np.ma.MaskedArray(prcs, np.isnan(prcs)).mean()
    overallwriter.writerow(write_overall_metric(basics, prcmean, 'PRC_AUC', np.nan, np.nan))
    prog.update(2)
    # and calibrated AUCs
    cal_rocs, cal_prcs = utils.mean_calibrated_roc_auc_prc_auc(ytrue, preds_multi)
    cal_rocmean = np.ma.MaskedArray(cal_rocs, np.isnan(cal_rocs)).mean()
    overallwriter.writerow(write_overall_metric(basics, cal_rocmean, 'calibrated_ROC_AUC', np.nan, np.nan))
    cal_prcmean = np.ma.MaskedArray(cal_prcs, np.isnan(cal_prcs)).mean()
    overallwriter.writerow(write_overall_metric(basics, cal_prcmean, 'calibrated_PRC_AUC', np.nan, np.nan))
    prog.update(2)
    overallcsv.close()
    
    # get individual species for topK spec
    for i in [1,5,30,100]:
        _, specs = utils.species_topK(single_ytrue, preds_single, i)
        writer.writerow(write_spec_metric(dict_, f'species_top{i}', i, specs, id2sp))
        prog.update(1)
    
    precsp, recsp, f1sp, supsp = mets.precision_recall_fscore_support(ytrue, yobs, zero_division=0)
    writer.writerow(write_spec_metric(dict_, 'ROC_AUC', np.nan, aucs, id2sp))
    writer.writerow(write_spec_metric(dict_, 'PRC_AUC', np.nan, prcs, id2sp))
    writer.writerow(write_spec_metric(dict_, 'calibrated_ROC_AUC', np.nan, cal_rocs, id2sp))
    writer.writerow(write_spec_metric(dict_, 'calibrated_PRC_AUC', np.nan, cal_prcs, id2sp))
    writer.writerow(write_spec_metric(dict_, 'precision_score', thres, precsp, id2sp))
    writer.writerow(write_spec_metric(dict_, 'recall_score', thres, recsp, id2sp))
    writer.writerow(write_spec_metric(dict_, 'f1_score', thres, f1sp, id2sp))
    writer.writerow(write_spec_metric(dict_, 'support', thres, supsp, id2sp))
    prog.update(8)
    csvfile.close()
    if write_obs:
        # print('starting per-observation metrics')
        fname = f"{paths.RESULTS}accuracy_metrics/{filename}_per_observations_metrics_results_band{band}.csv"
        fexists = os.path.isfile(fname)
        csvfile = open (fname, 'a')
        del basics['weight']
        basics['value'] = np.nan
        basics['ID'] = np.nan
        basics['thres'] = thres
        writer = csv.DictWriter(csvfile, delimiter=',', lineterminator='\n',fieldnames=basics.keys())
        if not fexists:
            writer.writeheader()  # file doesn't exist yet, write a header
        # finally, per-observation metrics
        basics['metric'] = f"precision_score"
        val = utils.precision_per_obs(yobs, ytrue)
        write_obs_metrics(basics, 'precision_score', val, ids, writer)
        prog.update(1)
        val =  utils.recall_per_obs(yobs, ytrue)
        write_obs_metrics(basics, 'recall_score', val, ids, writer) 
        prog.update(1)
        val =  utils.accuracy_per_obs(yobs, ytrue)
        write_obs_metrics(basics, 'accuracy_perobs', val, ids, writer)
        prog.update(1)
        val =  utils.f1_per_obs(yobs, ytrue)
        write_obs_metrics(basics, 'f1_score', val, ids, writer)
        prog.update(1)

        csvfile.close()  
    prog.close()
    tock = time.time()
    return (tock - tick)/60


def run_baseline_inference(model, band='unif_train_test', dset_name='big_cali_2012', state='ca', year=2012, threshold=.5, fname=None, writeobs=True):

    test_dset = dataset.DeepbioDataset(dset_name, 'BIOCLIM', 'MULTI_SPECIES', state, year, band, 'test', 'NONE')
    train_dset = dataset.DeepbioDataset(dset_name, 'BIOCLIM', 'MULTI_SPECIES', state, year, band, 'train', 'NONE', prep_onehots=False)
    shared_species = list(set(test_dset.pres_specs) & set(train_dset.pres_specs))
    
    preds = load_baseline_preds(model, len(test_dset), test_dset.nspec, test_dset.metadata.spec_2_id, test_dset.band, test_dset.dataset_name)

    y_pred_multi, y_pred_single, y_true_multi, y_true_single = run.filter_shared_species(preds, test_dset.all_specs_multi.numpy(), test_dset.specs.numpy(), shared_species) 

    evaluate_model(y_true_multi, y_true_single, y_pred_multi, y_pred_single, shared_species, test_dset.metadata.spec_2_id, test_dset.ids, dset_name, band, model,  np.nan,  np.nan,  np.nan, model, np.nan, np.nan, write_obs=writeobs, thres=threshold, filename=fname)


def run_inference(device, cfg, epoch, batchsize, nworkers=0, threshold=0.5, fname=None, writeobs=True):
    # load model
    test_dset = dataset.DeepbioDataset(cfg.dataset_name, cfg.datatype, cfg.dataset_type, cfg.state, cfg.year, cfg.band, 'test', cfg.augment)
    all_specs_multi, all_specs_single = test_dset.all_specs_multi.numpy(), test_dset.specs.numpy()

    train_dset = dataset.DeepbioDataset(cfg.dataset_name, cfg.datatype, cfg.dataset_type, cfg.state, cfg.year, cfg.band, 'train', cfg.augment, prep_onehots=False)
    shared_species = list(set(test_dset.pres_specs) & set(train_dset.pres_specs))
    
    model = run.load_model(device, cfg, epoch)
    model = model.eval()
    loss = run.instantiate_loss(cfg, train_dset, device)
    test_loader = DataLoader(test_dset, batchsize, shuffle=False, pin_memory=False, num_workers=nworkers, collate_fn=run.collate, drop_last=False)
    # run inference
    y_pred, _ = run.test_model(model, test_loader, loss, cfg, device)
    # convert to probabilities
    y_pred = torch.cat(y_pred, dim=0)
    y_pred = run.logit_to_proba(y_pred.cpu(), cfg.loss)
    # filter to only shared species
    y_pred_multi, y_pred_single, y_true_multi, y_true_single = run.filter_shared_species(y_pred, all_specs_multi, all_specs_single, shared_species) 

    return evaluate_model(y_true_multi, y_true_single, y_pred_multi, y_pred_single, shared_species, test_dset.metadata.spec_2_id, 
                                    test_dset.ids, cfg.dataset_name, cfg.band, cfg.model, cfg.loss, cfg.lr, epoch, cfg.exp_id, 
                                    cfg.pretrain, cfg.batchsize, filename=fname, write_obs=writeobs, thres=threshold)


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    # required ars
    args.add_argument('--band', type=str, help='Band which model to use for mapmaking was trained on', required=True)    
    args.add_argument('--model', type=str, help='what model to run inference on', required=True, choices=mods.valid() + ['rf', 'maxent'])
    # arguments for DL model
    args.add_argument('--exp_id', type=str, help='Experiment ID for model. Not necessary for baseline models')
    args.add_argument('--loss', type=str, help='Loss function used to train deep learnig model',  choices=losses.valid())
    args.add_argument('--epoch', type=int, help='what model epoch to evaluate deep learning model')
    args.add_argument('--batch_size', type=int, help='what size batch to use for making map inference', default=10)
    args.add_argument('--device', type=int, help="Which CUDA device to use. Set -1 for CPU", default=-1)
    args.add_argument('--processes', type=int, help="How many worker processes to use for mapmaking", default=1)
    # arguments for baselines
    args.add_argument('--state', type=str, help='What state predictions are being made int', default='ca')
    args.add_argument('--year', type=int, help='what year of NAIP data should be used', default=2012)
    args.add_argument('--dataset_name', type=str, help='what dataset was used to fit the model', default='big_cali_2012')
    # generic options
    args.add_argument('--filename', type=str, help='What to call results table')
    args.add_argument('--writeobs', action='store_true', help="Whether to also write per-obs acc. metris", default=True)
    args.add_argument('--threshold', type=float, help='what value to threshold for presence/absence predictions', default=0.5)

    args, _ = args.parse_known_args()
  
    if args.model in ['rf', 'maxent']:
        run_baseline_inference(args.model, args.band, args.dataset_name, args.state, args.year, args.threshold, args.filename, args.writeobs)
    else:
        cnn = {
            'exp_id': args.exp_id,
            'band' : args.band, 
            'loss': args.loss,
            'model': args.model
        }
        cfg = run.load_config(**cnn)
        device = f"cuda:{args.device}" if int(args.device) >= 0 else 'cpu'
        run_inference(device, cfg, args.epoch, args.batch_size, args.processes, args.threshold, args.filename, args.writeobs)