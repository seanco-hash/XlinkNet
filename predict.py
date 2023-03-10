import argparse
import multiprocessing
import sys
import os
import shutil
import torch
import traceback
import seaborn as sns
import random
from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.MMCIFParser import MMCIFParser
from Bio import PDB, SeqIO
import pdb_files_manager
import cross_link
import general_utils
import train
import graph_dataset
import data_proccess
import numpy as np
import copy
import matplotlib.pyplot as plt


# device = train.device
device = 'cpu'


def count_increase_decrease(d):
    tot = 0
    if d[3] > 0:
        tot += d[3]
        if d[2] > 0:
            tot += d[2]
        elif d[3] + d[2] < 0:
            tot += d[3] + d[2]
        if d[1] > 0:
            tot += d[1]
        if d[0] > 0:
            tot -= d[0]
    else:
        tot += d[3]
        if d[2] < 0:
            tot += d[2]
        elif d[3] + d[2] > 0:
            tot += d[3] + d[2]
        if d[1] < 0:
            tot += d[1]
        if d[0] < 0:
            tot -= d[0]
    return tot



def plot_total_ablation_heatmaps(data, title='', xlabel='', ylabel='', is_xticks=True):
    # data = np.log(data)
    general_utils.initialize_plt_params()
    idx_to_aa_dict = {v: k for k, v in pdb_files_manager.AA_TABLE_IDX.items()}
    ysticks = [idx_to_aa_dict[i] for i in range(len(data))]
    if is_xticks:
        xsticks = [idx_to_aa_dict[i] for i in range(len(data[0]))]
    else:
        xsticks = [i for i in range(len(data[0]))]
    ax = sns.heatmap(data, linewidth=0.5, vmin=-0.1, vmax=0.1, yticklabels=ysticks, xticklabels=xsticks,
                     cmap=sns.color_palette("vlag", as_cmap=True))
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.show()


def plot_single_change_ablation_heatmaps(data):
    idx_to_aa_dict = {v: k for k, v in pdb_files_manager.AA_TABLE_IDX.items()}
    ysticks = [idx_to_aa_dict[i] for i in range(20)]
    for i in range(data.shape[0]):
        ax = sns.heatmap(data[i], linewidth=0.5, vmin=np.min(data), vmax=np.max(data), yticklabels=ysticks)
        plt.title(f"Prediction Changes Replacing {idx_to_aa_dict[i]}")
        plt.show()


def clear_empty_files():
    base_dir = '/cs/labs/dina/seanco/xl_parser/scwrl/'
    dirs = ['pred_changes/', 'label_changes/', 'counters/']
    to_remove = []
    for d in dirs:
        cur_dir = base_dir + d
        for f in os.listdir(cur_dir):
            np_arr = np.load(cur_dir + f)
            if not np_arr.any():
                to_remove.append(cur_dir + f)
    for f in to_remove:
        os.unlink(f)


def read_ablation_results():
    base_dir = '/cs/labs/dina/seanco/xl_parser/scwrl/'
    dirs = ['pred_changes/', 'label_changes/', 'counters/']
    total_pred_probs = np.zeros((len(pdb_files_manager.EXTENDED_AA_LETTERS), len(pdb_files_manager.AA_LETTERS), 4))
    total_pred_labels = np.zeros((len(pdb_files_manager.EXTENDED_AA_LETTERS), len(pdb_files_manager.AA_LETTERS), 4))
    total_num_samples = np.zeros((len(pdb_files_manager.EXTENDED_AA_LETTERS), len(pdb_files_manager.AA_LETTERS)))
    for f in os.listdir(base_dir + dirs[0]):
        total_pred_probs += np.load(base_dir + dirs[0] + f)
        if os.path.isfile(base_dir + dirs[1] + f):
            total_pred_labels += np.load(base_dir + dirs[1] + f)
        total_num_samples += np.load(base_dir + dirs[2] + f)
    # total_pred_labels[8] = 0
    # total_pred_labels[:, 8] = 0
    total_pred_probs /= np.reshape(total_num_samples, (total_num_samples.shape[0], total_num_samples.shape[1], 1))
    total_pred_probs[np.isnan(total_pred_probs)] = 0
    most_changed_from_aa = np.sum(total_pred_labels, axis=1)[:20]
    most_changed_to_aa = np.sum(total_pred_labels, axis=0)
    total_pred_labels /=  np.reshape(total_num_samples, (total_num_samples.shape[0], total_num_samples.shape[1], 1))
    total_pred_labels[np.isnan(total_pred_labels)] = 0
    inc_dec_change = np.apply_along_axis(count_increase_decrease, 2, total_pred_labels[:20, :])
    plot_total_ablation_heatmaps(inc_dec_change, "", 'New AA', 'Original AA')
    # plot_total_ablation_heatmaps(total_pred_labels[:20, :, 0], "", '', 'Original AA')
    # plot_total_ablation_heatmaps(total_pred_labels[:20, :, 1], "", '', '')
    # plot_total_ablation_heatmaps(total_pred_labels[:20, :, 2], "", 'New AA', 'Original AA')
    # plot_total_ablation_heatmaps(total_pred_labels[:20, :, 3], "", 'New AA', '')
    # plot_total_ablation_heatmaps(most_changed_from_aa, "Label Changes of Replacing specific AA to any other AA", 'Predicted Labels', 'Original AA')
    # plot_total_ablation_heatmaps(most_changed_to_aa, "Label Changes of Replacing from any AA to specific AA", 'Predicted Labels', 'New AA')
    # plot_single_change_ablation_heatmaps(total_pred_labels)
    # plot_ablation_heatmaps(total_pred_probs)


def get_pdb_file_list_of_object(obj):
    if obj.pdb_path[-3:] == 'pdb':
        pdb_file = [obj.pdb_path]
    else:
        pref, suff = obj.pdb_path.split('.')
        pdb_file = [f"{pref}_{obj.chain_a}.{suff}"]
        if obj.chain_a != obj.chain_b:
            pdb_file += [f"{pref}_{obj.chain_b}.{suff}"]
    return pdb_file


def extract_features_single_object(out_dir, pdb_files, pdb_name, obj,
                                   xl_dir=pdb_files_manager.INTER_AND_INTRA_LYS_XL_FILES_PATH):
    xl_file = xl_dir + pdb_name + '.txt'
    xl_feat_path = f"{out_dir}features/"
    if not os.path.isdir(xl_feat_path):
        os.makedirs(xl_feat_path)
    pdb_files_manager.single_thread_extract_xl_features([xl_file], [pdb_files], output_path=xl_feat_path,
                                                        predict=True)
    feat_files = [xl_feat_path + pdb.split('/')[-1].split('.')[0] + '.txt' for pdb in pdb_files]
    feat_dict = dict()
    dict_keys = [pdb_name, pdb_name] if obj.pdb_path[-3:] == 'pdb' else [f"{pdb_name}_{obj.chain_a}", f"{pdb_name}_{obj.chain_b}"]
    pdb_files_manager.predict_read_features(pdb_files, feat_dict, feat_files, keys=dict_keys)
    return feat_dict


def predict_single_object(obj, cfg, model, out_dir, pdb_files, pdb_name, old_aa=None, new_aa=None, cur_chain=None):
    feat_dict = extract_features_single_object(out_dir, pdb_files, pdb_name, obj)
    if old_aa is None:
        dataset_name = f"{obj.pdb_path.split('.')[0].split('/')[-1]}_{obj.chain_a}_{obj.res_num_a}_{obj.chain_b}_{obj.res_num_b}"
    else:
        dataset_name = f"{obj.pdb_path.split('.')[0].split('/')[-1]}_{cur_chain}_{obj.res_num_a}_{old_aa}_{new_aa}"
    graph_dataset.generate_graph_data([obj], feat_dict, None, None, dataset_name, None, edge_dist_th=3,
                                      predict=False)
    cfg['dataset'] = dataset_name
    labels, probas = predict(cfg, [obj], False, None, None, model, False)
    dataset_dir = graph_dataset.ROOT_DATA_DIR + dataset_name
    shutil.rmtree(dataset_dir + '/', ignore_errors=True)
    if os.path.isfile(dataset_dir + '.pkl'):
        os.unlink(dataset_dir + '.pkl')
    return labels, probas


def ablation_study_create_mutation_files(xl_objects = None):
    if xl_objects is None:
        xl_objects = general_utils.load_obj('ablation_objects')
        xl_objects = sorted(xl_objects, key=lambda o: o.pdb_path)
    prev_pdb = ''
    pdb_parser = PDBParser(PERMISSIVE=1)
    closest_dict = general_utils.load_obj('closest_residues')
    for i, obj in enumerate(xl_objects):
        if obj.pdb_path != prev_pdb:
            seq_dict = {}
            if obj.pdb_path[-3:] == 'cif':
                continue
            else:
                structure = pdb_parser.get_structure(obj.pdb_path.split('/')[-1], obj.pdb_path)
            chains = list(structure.get_chains())
        seq_a, seq_b = pdb_files_manager.get_sequences_for_obj(obj, chains, seq_dict)
        pref, suff = obj.pdb_path.split('.')
        closest_a = closest_dict[obj.pdb_path][obj.chain_a][obj.res_num_a]
        pdb_a = obj.pdb_path if len(chains) == 1 else f"{pref}_{obj.chain_a}.{suff}"
        pdb_files_manager.create_scwrl_mutation_files(obj.res_num_a, obj.chain_a, closest_a, pdb_a,
                                                      copy.deepcopy(seq_a), pdb_files_manager.SCWRL_OUT_DIR)
        closest_b = closest_dict[obj.pdb_path][obj.chain_b][obj.res_num_b]
        pdb_b = pdb_a if obj.chain_a == obj.chain_b else f"{pref}_{obj.chain_b}.{suff}"
        pdb_files_manager.create_scwrl_mutation_files(obj.res_num_b, obj.chain_b, closest_b, pdb_b,
                                                      copy.deepcopy(seq_b),
                                                      pdb_files_manager.SCWRL_OUT_DIR)
        prev_pdb = obj.pdb_path


def remove_dirs_and_files(dir_path):
    folder = dir_path
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path, ignore_errors=True)
        except Exception as e:
            print('Failed to delete %s. Reason: %s' % (file_path, e))


def ablation_study_objects_with_same_pdb(xl_objects, cfg, pid=None, scwrl_dir=pdb_files_manager.SCWRL_OUT_DIR):
    print(f"start ablation process: {pid}")
    print(sys.__stdout__)
    print(sys.__stdout__.fileno())
    closest_dict = general_utils.load_obj('closest_residues')
    ablation_study_create_mutation_files(xl_objects)
    model = train.get_model(cfg)
    _optimizer = train.construct_optimizer(model.parameters(), cfg)
    model, _ = train.load_model(cfg, model, _optimizer, is_cpu=True)
    model.to(device)
    model.eval()
    pdb_name = xl_objects[0].pdb_path.split('/')[-1].split('.')[0]
    out_dir = f"{scwrl_dir}{pdb_name}/"
    pred_changes = np.zeros((len(pdb_files_manager.EXTENDED_AA_LETTERS), len(pdb_files_manager.AA_LETTERS), cfg['num_classes']))
    label_changes = np.zeros((len(pdb_files_manager.EXTENDED_AA_LETTERS), len(pdb_files_manager.AA_LETTERS), cfg['num_classes']))
    count_samples = np.zeros((len(pdb_files_manager.EXTENDED_AA_LETTERS), len(pdb_files_manager.AA_LETTERS)))
    for obj in xl_objects:
        try:
            pdb_files = get_pdb_file_list_of_object(obj)
            orig_labels, orig_probas = predict_single_object(obj, cfg, model, out_dir, pdb_files, pdb_name)
            for r, (chain, res_num) in enumerate([(obj.chain_a, obj.res_num_a), (obj.chain_b, obj.res_num_b)]):
                closest = closest_dict[obj.pdb_path][chain][res_num]
                new_out_dir = f"{scwrl_dir}{pdb_name}/{chain}/{res_num}/"
                for i, c in enumerate(closest):
                    old_aa = c[1]
                    old_aa_table_idx = pdb_files_manager.AA_TABLE_IDX[old_aa]
                    for j, aa in enumerate(pdb_files_manager.AA_LETTERS):
                        if aa != old_aa:
                            new_pdb = new_out_dir + str(c[0]) + '_' + old_aa + '_' + aa + '.pdb'
                            if os.path.isfile(new_pdb):
                                new_pdb_files = copy.deepcopy(pdb_files)
                                if len(new_pdb_files) > 1:
                                    new_pdb_files[r] = new_pdb
                                else:
                                    new_pdb_files[0] = new_pdb
                                labels, probas = predict_single_object(obj, cfg, model, out_dir, new_pdb_files, pdb_name, old_aa, aa, chain)
                                pred_changes[old_aa_table_idx, j] += (probas[0] - orig_probas[0])
                                label_changes[old_aa_table_idx, j, int(orig_labels[0])] -= 1
                                label_changes[old_aa_table_idx, j, int(labels[0])] += 1
                                count_samples[old_aa_table_idx, j] += 1
        except Exception as e:
            print(traceback.format_exc())
            print(e)
            print(f"problem with obj: {obj.pdb_path}")
    if pid is not None and pred_changes.any():
        print(f"saving {pid}")
        np.save(f"{scwrl_dir}pred_changes/{pid}.npy", pred_changes)
        np.save(f"{scwrl_dir}label_changes/{pid}.npy", label_changes)
        np.save(f"{scwrl_dir}counters/{pid}.npy", count_samples)
    else:
        print(f"not saving {pid}")
        return pred_changes, label_changes, count_samples
    remove_dirs_and_files(out_dir)


def run_ablation_single_process(object_lists, cfg):
    pred_changes = np.zeros((len(pdb_files_manager.EXTENDED_AA_LETTERS), len(pdb_files_manager.AA_LETTERS), cfg['num_classes']))
    label_changes = np.zeros((len(pdb_files_manager.EXTENDED_AA_LETTERS), len(pdb_files_manager.AA_LETTERS), cfg['num_classes']))
    total_num_damples = 0
    for lst in object_lists:
        p, l, c = ablation_study_objects_with_same_pdb(lst, cfg, 1)
        pred_changes += p
        label_changes += l
        total_num_damples += c
    pred_changes = pred_changes / total_num_damples
    label_changes = label_changes / total_num_damples
    general_utils.save_obj(pred_changes, "ablation_pred_changes")
    general_utils.save_obj(label_changes, "ablation_label_changes")


def run_ablation_multi_process(object_lists, cfg):
    processes = []
    available_cpus = len(os.sched_getaffinity(0)) - 1
    print(f"start run parallel. available cpus: {available_cpus}")
    for pid in range(available_cpus):
        objects = copy.deepcopy(object_lists[pid])
        p = multiprocessing.Process(target=ablation_study_objects_with_same_pdb,
                                args=(objects, copy.deepcopy(cfg), pid))
        processes.append(p)
        p.start()
    for p in processes:
        p.join()


def ablation_study(cfg_path="/cs/labs/dina/seanco/xl_mlp_nn/configs/gnn_47f.yaml", run_parallel=True):
    cfg = train.load_config(None, cfg_path)
    xl_objects = general_utils.load_obj('ablation_objects')
    xl_objects = sorted(xl_objects, key=lambda o: o.pdb_path)
    i = 0
    object_lists = []
    while i < len(xl_objects):
        prev_pdb = xl_objects[i].pdb_path
        same_pdb_objects = []
        while i < len(xl_objects) and prev_pdb == xl_objects[i].pdb_path:
            same_pdb_objects.append(xl_objects[i])
            i += 1
        object_lists.append(same_pdb_objects)
    print("before run parallel")
    if run_parallel:
        run_ablation_multi_process(object_lists, cfg)
    else:
        run_ablation_single_process(object_lists, cfg)


def update_xlink_file_to_dimeric(in_file, out_file, chain_dimer_dict):
    in_f = open(in_file, 'r')
    out_f = open(out_file, 'w')
    for line in in_f:
        words = line.split()
        if words[1] == words[3] and len(words[1]) == 1 and words[1] not in chain_dimer_dict:
            continue
        if words[1] in chain_dimer_dict:
            words[1] = words[1] + chain_dimer_dict[words[1]]
        if words[3] in chain_dimer_dict:
            words[3] = words[3] + chain_dimer_dict[words[3]]
        new_line = " ".join(words) + '\n'
        out_f.write(new_line)
    out_f.close()
    in_f.close()


def preprocess_xlink_file(in_file, out_file, dimers):
    chain_dimer_dict = dict()
    pairs = dimers.split()
    for pair in pairs:
        chain_dimer_dict[pair[0]] = pair[1]
        chain_dimer_dict[pair[1]] = pair[0]
    update_xlink_file_to_dimeric(in_file, out_file, chain_dimer_dict)


def fix_prediction_file_by_removing_dup(file_path):
    in_f = open(file_path, 'r')
    line_distance = dict()
    lines = dict()
    for line in in_f:
        words = line.split()
        res_chain_pref = ' '.join(words[:4])
        res_chain_opp = f"{words[2]} {words[3]} {words[0]} {words[1]}"
        if res_chain_pref in line_distance:
            if res_chain_pref in lines:
                key = res_chain_pref
            else:
                key = res_chain_opp
            max_probs_old = max([float(s) for s in lines[key].split()[6:]])
            max_probs_new = max([float(s) for s in words[6:]])
            if max_probs_new > 0.98 and max_probs_new > max_probs_old: # throws high probabilities to deal overfit
                continue
            if (float(words[4]) > line_distance[res_chain_pref] and max_probs_old > 0.5) or max_probs_new > 0.95 > max_probs_old:
                continue
        line_distance[res_chain_pref] = float(words[4])
        line_distance[res_chain_opp] = float(words[4])
        lines[res_chain_pref] = line
    in_f.close()
    out_f = open(file_path, 'w')
    for line in lines.values():
        out_f.write(line)
    out_f.close()


def print_pred_to_file(obj, min_dist, max_dist, y_pred_prob, out_file, dimer_dict=None):
    y_pred_prob = [str(item) for item in y_pred_prob]
    probs_str = " ".join(y_pred_prob)
    if dimer_dict is None:
        chain_a = obj.uniport_a
        chain_b = obj.uniport_b
    else:
        chain_a = dimer_dict[obj.uniport_a]
        chain_b = dimer_dict[obj.uniport_b]
    out_file.write(f"{obj.res_num_a} {chain_a} {obj.res_num_b} {chain_b} {min_dist} {max_dist},"
                   f" {probs_str}\n")


def print_prediction(obj, label, cfg, y_pred_prob, validate=True, out_file=None, dimer_dict=None):
    min_dist, max_dist = graph_dataset.XlPairGraphDataset.get_dist_from_label(label, cfg['model_th'])
    print(f"Cross link: {obj.res_num_a} {obj.uniport_a} {obj.res_num_b} "
          f"{obj.uniport_b}\nPredicted range: {min_dist} - {max_dist} \nProbabilities: {y_pred_prob}")
    if validate:
        print(f"True distance in pdb: {obj.distance}")
    if out_file is not None:
        print_pred_to_file(obj, min_dist, max_dist, y_pred_prob, out_file, dimer_dict)


def create_fake_xl_objects(pdb_name, amount=50, linker='DSS', max_distance=45):
    uniport = pdb_name.split('/')[-1].split('.')[0]
    pdb_parser = PDBParser(PERMISSIVE=1)
    ppb = PDB.CaPPBuilder()
    structure = pdb_parser.get_structure(pdb_name.split('/')[-1], pdb_name)
    polypeptide_list = ppb.build_peptides(structure, 1)
    lys_residues = []
    xl_objets = []
    for pep in polypeptide_list:
        for res in pep:
            if res.resname == 'LYS':
                lys_residues.append(res)
    for i in range(len(lys_residues)):
        for j in range(i + 1, len(lys_residues)):
            obj = cross_link.CrossLink("", "", lys_residues[i].id[1], uniport, "", "",
                                       lys_residues[j].id[1], uniport, linker, uniport)
            xl_objets.append(obj)
    random.shuffle(xl_objets)
    for obj in xl_objets:
        obj.process_single_xl(polypeptide_list)
    xl_objets = [obj for obj in xl_objets if obj.distance <= max_distance]
    xl_objets = xl_objets[:amount]
    return xl_objets


def fake_predict(cfg, data_name, xl_objects=None, best_prob=0.8, rand_prob=0.1, validate=True,
                 out_file=None, dimer_dict=None):
    if xl_objects is None:
        xl_objects = create_fake_xl_objects(data_name)
    distances = [obj.distance for obj in xl_objects]
    distances = np.asarray(distances)
    labels, th = data_proccess.FeatDataset.get_labels_from_dist(np.copy(distances), cfg['num_classes'],
                                                                cfg['model_th'])
    labels = labels.astype(int)
    pred_probs = np.zeros((len(xl_objects), cfg['num_classes']))
    for i, obj in enumerate(xl_objects):
        true_label = labels[i]
        if true_label > 0:
            sec_label = true_label - 1
        else:
            sec_label = true_label + 1
        if true_label == cfg['num_classes'] - 1:
            third_label = true_label - 2
        else:
            third_label = true_label + 1
        p1 = random.uniform(0.5, 1)
        p2 = random.uniform(0, 1 - p1)
        p3 = 1 - (p1 + p2)
        p = random.uniform(0, 1)
        if p < best_prob:
            pred_probs[i][true_label] = p1
            pred_probs[i][sec_label] = p2
            pred_probs[i][third_label] = p3
        elif p > (1 - rand_prob):
            l1, l2, l3 = random.sample(range(cfg['num_classes']), 3)
            pred_probs[i][l1] = p1
            pred_probs[i][l2] = p2
            pred_probs[i][l3] = p3
        else:
            pred_probs[i][true_label] = p2
            pred_probs[i][sec_label] = p1
            pred_probs[i][third_label] = p3
        print_prediction(obj, labels[i], cfg, pred_probs[i], validate, out_file, dimer_dict)
    train.plot_cm(labels, pred_probs)
    return xl_objects, labels, pred_probs


def predict(cfg, xl_objects, validate=True, out_file=None, dimer_dict=None, model=None, to_print=True):
    if model is None:
        model = train.get_model(cfg)
        _optimizer = train.construct_optimizer(model.parameters(), cfg)
        model, _ = train.load_model(cfg, model, _optimizer)
        model.to(device)
        model.eval()
    _, dataset = train.get_dataset(cfg)
    data_loader, _ = train.load_data(cfg, dataset, None, shuffle=False)
    probas = np.zeros((len(xl_objects), cfg['num_classes']))
    labels = np.zeros(len(xl_objects))
    with torch.no_grad():
        for i, data in enumerate(data_loader):
            inputs = data.to(device)
            outputs = model(inputs)
            y_pred_prob = torch.softmax(outputs[0], dim=1)
            _, y_pred_tags = torch.max(y_pred_prob, dim=1)
            labels[i] = (y_pred_tags.item())
            probas[i] = y_pred_prob.cpu().numpy()
            if to_print:
                print_prediction(xl_objects[i], y_pred_tags.item(), cfg, y_pred_prob.cpu().tolist()[0],
                                 validate, out_file, dimer_dict)
        return labels, probas


def initialize_obj_angles(obj):
    obj.omega = np.array([1, 1])
    obj.phi = np.array([1, 1, 1, 1])
    obj.theta = np.array([1, 1, 1, 1])


def create_xl_obj_in_dimer_xl(chain_a, chain_b, res_a, res_b, linker, objects, peptides, dimer_dict):
    # best_obj = None
    errors = 0
    for c_a in chain_a:
        for c_b in chain_b:
            dimer_dict[c_a] = chain_a
            dimer_dict[c_b] = chain_b
            obj = cross_link.CrossLink("", "", res_a, c_a, "", "",
                                       res_b, c_b, linker)
            # obj.process_single_xl(peptides, True)
            errors += obj.process_single_xl(None, True, peptides)
            initialize_obj_angles(obj)
            # if best_obj is None or 0 < obj.distance < best_obj.distance:
            #     best_obj = obj
            objects.append(obj)
    print(f"total objects: {len(objects)}, errors in find distance: {errors}")


def create_multichain_xl_obj(chain_a, chain_b, res_a, res_b, linker, objects, peptides, dimer_dict, validate):
    if validate and (len(chain_a) > 1 or len(chain_b) > 1):
        create_xl_obj_in_dimer_xl(chain_a, chain_b, res_a, res_b, linker, objects, peptides, dimer_dict)
    else:
        obj = cross_link.CrossLink("", "", res_a, chain_a[0], "", "", res_b, chain_b[0], linker)
        if validate:
            obj.process_single_xl(None, True, peptides)
        initialize_obj_angles(obj)
        objects.append(obj)
        dimer_dict[chain_a[0]] = chain_a
        dimer_dict[chain_b[0]] = chain_b


def create_xl_objects_multiple_pdb(xl_file, linker, solution_pdb=None, validate=False):
    objects = []
    dimer_dict = dict()
    peptides = None
    if validate and solution_pdb is not None:
        suff = solution_pdb.split('.')[-1]
        if suff == 'cif':
            pdb_parser = MMCIFParser()
        else:
            pdb_parser = PDBParser(PERMISSIVE=1)
        structure = pdb_parser.get_structure(solution_pdb.split('/')[-1], solution_pdb)
        peptides = list(structure.get_chains())
    with open(xl_file, 'r') as f:
        for line in f:
            res_a, chain_a, res_b, chain_b, min_dist, max_dist = line.split(' ')
            max_dist = max_dist[:-1] # clear \n
            tmp_linker = linker
            if max_dist == '35' and linker != 'BDP-NHP':
                tmp_linker = 'BDP-NHP'
            elif max_dist == '32' and linker == 'BDP-NHP':
                tmp_linker = 'DSSO'
            create_multichain_xl_obj(chain_a, chain_b, res_a, res_b, tmp_linker, objects, peptides, dimer_dict, validate)
    return objects, dimer_dict


def create_xl_objects_single_pdb(xl_file, pdb_name, linker, validate=False, multichain=False):
    objects = []
    dimer_dict = dict()
    polypeptide_list, chains = None, None
    uniport = pdb_name.split('/')[-1].split('.')[0]
    if validate:
        pdb_parser = PDBParser(PERMISSIVE=1)
        ppb = PDB.CaPPBuilder()
        structure = pdb_parser.get_structure(pdb_name.split('/')[-1], pdb_name)
        polypeptide_list = ppb.build_peptides(structure, 1)
        chains = list(structure.get_chains())
    with open(xl_file, 'r') as f:
        for line in f:
            res_a, chain_a, res_b, chain_b, _, _ = line.split(' ')
            if not multichain:
                obj = cross_link.CrossLink("", "", res_a, uniport, "", "",
                                           res_b, uniport, linker, uniport)
                peptides = polypeptide_list
                if validate:
                    obj.process_single_xl(peptides, multichain)
                initialize_obj_angles(obj)
                objects.append(obj)
            else:
                peptides = chains
                create_multichain_xl_obj(chain_a, chain_b, res_a, res_b, linker, objects, peptides,
                                         dimer_dict, validate)
    return objects, dimer_dict


def update_feat_dict_by_dimers(feat_dict, dimer_dict):
    new_dict = dict()
    for key, val in feat_dict.items():
        if key in dimer_dict:
            for new_key in dimer_dict[key]:
                if key != new_key and len(feat_dict[new_key]) == 0:
                    new_dict[new_key] = val
    feat_dict.update(new_dict)


def check_if_chain_relevant(uniport, dimer_dict, relevant_chains):
    if uniport in relevant_chains:
        return True
    if uniport in dimer_dict:
        opt_chains = dimer_dict[uniport]
        for c in opt_chains:
            if c in relevant_chains:
                return True
    return False


def filter_irrelevant_xl_objects(xl_objects, pdbs, dimer_dict):
    relevant_chains = set()
    relevant = []
    for pdb in pdbs:
        chain = pdb.split('/')[-1].split('.')[0].split('_')[0]
        relevant_chains.add(chain)
    for obj in xl_objects:
        a = check_if_chain_relevant(obj.uniport_a, dimer_dict, relevant_chains)
        b = check_if_chain_relevant(obj.uniport_b, dimer_dict, relevant_chains)
        if a and b and (obj.uniport_a != obj.uniport_b or
                        (obj.uniport_a in dimer_dict and obj.uniport_a != dimer_dict[obj.uniport_a])):
            relevant.append(obj)
    return relevant


def pre_process_data(xl_file, pdb_file, linker, solution_pdb, multichain):
    data_name = xl_file.split('/')[-1].split('.')[0]
    if len(pdb_file) == 1:
        xl_objects, dimer_dict = create_xl_objects_single_pdb(xl_file, pdb_file, linker,
                                                              multichain)
    else:
        xl_objects, dimer_dict = create_xl_objects_multiple_pdb(xl_file, linker,
                                                                solution_pdb, True)
    xl_objects = filter_irrelevant_xl_objects(xl_objects, pdb_file, dimer_dict)
    xl_objects = cross_link.CrossLink.clear_duplicates_of_xl_objects(xl_objects, True)
    xl_feat_path = pdb_files_manager.XL_NEIGHBORS_FILES_PATH + 'predict/'
    if not os.path.isdir(xl_feat_path):
        os.makedirs(xl_feat_path)
    pdb_files_manager.single_thread_extract_xl_features([xl_file], [pdb_file], output_path=xl_feat_path, predict=True)
    xl_files_path = [xl_feat_path + pdb.split('/')[-1].split('.')[0] + '.txt' for pdb in pdb_file]
    feat_dict = dict()
    pdb_files_manager.predict_read_features(pdb_file, feat_dict, xl_files_path)
    update_feat_dict_by_dimers(feat_dict, dimer_dict)
    graph_dataset.generate_graph_data(xl_objects, feat_dict, None, None, data_name, pdb_file, edge_dist_th=3, predict=True)
    return data_name, xl_objects, dimer_dict


def write_th_file(out_path, cfg):
    th_path = out_path + 'th_file.txt'
    with open(th_path, 'w') as f:
        th = cfg['model_th']
        for i in range(len(th) - 1):
            f.write(f"{th[i]} ")
        f.write(str(th[-1]))
    return th_path


def parse_args():
    parser = TrainingParser()
    args = parser.parse_args()
    TrainingParser.validate_args(args)
    return args


class TrainingParser(argparse.ArgumentParser):

    def __init__(self, **kwargs):
        super(TrainingParser, self).__init__(**kwargs)
        self.add_argument(
            "--cfg",
            help="Path to the config file",
            default="/cs/labs/dina/seanco/xl_mlp_nn/configs/predict_config.yaml",
            type=str,
        )
        self.add_argument(
            "--xl",
            help="Path to Cross Links file in format: residue_number_a chain_id_a residue_number_b "
                 "chain_id_b min_distance max_distance",
            # default='None',
            # default='/cs/labs/dina/seanco/DockingXlScore/data/CASP13_target/xlinks.txt',
            # default='/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/pdb6jxd.txt',
            default='/cs/labs/dina/seanco/xl_mlp_nn/predictions/6cp8/pdb6cp8.txt',
            # default='/cs/labs/dina/seanco/Tric/xl/parsed_xl_32.txt',
            # default='/cs/labs/dina/seanco/xl_neighbors/xl_files/P75506.txt',
            type=str,
        )
        self.add_argument(
            "--original_xl",
            help="Path to Cross Links file in format: residue_number_a chain_id_a residue_number_b "
                 "chain_id_b min_distance max_distance. Given only if this file needs update to dimeric form",
            # default='/cs/labs/dina/seanco/xl_neighbors/unfiltered_xl_files/pdb1ujz.txt',
            default=None,
            type=str,
        )
        self.add_argument(
            "--chain_dimer_dict",
            help="pairs of dimeric chain id. for examle: AD BF CE ",
            # default="AE BF CG DH",
            default="",
            type=str,
        )
        self.add_argument(
            "--pdb",
            help="Path to pdb files",
            # default=['/cs/labs/dina/seanco/DockingXlScore/data/CASP13_target/A.pdb',
            #          '/cs/labs/dina/seanco/DockingXlScore/data/CASP13_target/B.pdb'],
            default=['/cs/labs/dina/seanco/xl_mlp_nn/predictions/6cp8/A_tr.pdb',
                     '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6cp8/B_tr.pdb'],
                     # '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/C_tr.pdb',
                     # '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/D_tr.pdb',
                     # '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/E_tr.pdb',
                     # '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/F_tr.pdb',
                     # '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/G_tr.pdb',
                     # '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/H_tr.pdb',
                     # '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/I_tr.pdb',
                     # '/cs/labs/dina/seanco/xl_mlp_nn/predictions/6jxd/J_tr.pdb'],
                     # '/cs/labs/dina/seanco/xl_parser/pdbs/pdb6jxd_C.ent',
                     # '/cs/labs/dina/seanco/xl_parser/pdbs/pdb6jxd_D.ent',
                     # '/cs/labs/dina/seanco/xl_parser/pdbs/pdb6jxd_E.ent',
                     # '/cs/labs/dina/seanco/xl_parser/pdbs/pdb6jxd_F.ent',
                     # '/cs/labs/dina/seanco/xl_parser/pdbs/pdb6jxd_G.ent',
                     # '/cs/labs/dina/seanco/xl_parser/pdbs/pdb6jxd_H.ent'],
            # default='/cs/labs/dina/seanco/xl_parser/pdbs/alpha_fold/pdb_files/P75506.pdb',
            nargs='+'
        )

        self.add_argument(
            "--solution_pdb",
            help="(optional) Path to solution pdb of multichain protein",
            default='/cs/labs/dina/seanco/xl_parser/pdbs/pdb6cp8_AB.ent',
            # default='/cs/labs/dina/seanco/DockingXlScore/data/CASP13_target/A_B.pdb',
            # default='/cs/labs/dina/seanco/Tric/tric_align/debug_res.pdb',
            type=str
        )

        self.add_argument(
            "--out_path",
            help="Path to prediction output file",
            default='/cs/labs/dina/seanco/xl_mlp_nn/predictions/6cp8/',
            # default='/cs/labs/dina/seanco/DockingXlScore/data/CASP13_target/fake_prediction.txt',
            # default='/cs/labs/dina/seanco/Tric/input/fake_prediction.txt',
            type=str
        )

        self.add_argument(
            "--linker",
            help="Linker type. one of: DSSO, DSS, BDP_NHP UNKNOWN LEIKER",
            # default='BDP-NHP',
            default='DSSO',
            type=str
        )

        self.add_argument(
            "--multichain",
            help="Is the protein single or multi chain",
            default=True,
            type=bool
        )

    @staticmethod
    def validate_args(args):
        if args.cfg is None or not os.path.isfile(args.cfg):
            raise argparse.ArgumentTypeError(f"Invalid config file path: {args.cfg}")
        if args.linker not in cross_link.LINKER_DICT:
            raise argparse.ArgumentTypeError(f"Invalid linker type: {args.linker}")

    def parse_args(self, args=None, namespace=None):
        """ Parse the input arguments """
        args = super(TrainingParser, self).parse_args(args, namespace)
        return args


def run_prediction(cfg_path, out_path, xl_file, pdb_files, linker, multichain, solution_pdb, original_xl=None, dimers=None):
    res_file = out_path + 'pred_xlinks.txt'
    train.seed_everything()
    out_file = None
    if not os.path.isdir(out_path):
        os.makedirs(out_path)
    cfg = train.load_config(None, cfg_path)
    if cfg['output_to_file']:
        out_file = open(res_file, 'w')
    if xl_file != 'None':
        if original_xl is not None and dimers is not None:
            preprocess_xlink_file(original_xl, xl_file, dimers)
        data_name, xl_objects, dimer_dict = pre_process_data(xl_file, pdb_files, linker, solution_pdb, multichain)
        cfg['dataset'] = data_name
        if cfg['predict_type'] == 'real':
            predict(cfg, xl_objects, out_file=out_file, dimer_dict=dimer_dict)
        else:
            fake_predict(cfg, None, xl_objects, out_file=out_file, dimer_dict=dimer_dict)
    else:
        fake_predict(cfg, pdb_files[0], None, out_file=out_file)
    if cfg['output_to_file']:
        out_file.close()
        fix_prediction_file_by_removing_dup(res_file)
    th_path = write_th_file(out_path, cfg)
    return th_path, res_file


def main():
    print("start predict")

    _args = parse_args()
    th_path, pred_xl_res_file = run_prediction(_args.cfg, _args.out_path, _args.xl, _args.pdb, _args.linker, _args.multichain,
                                               _args.solution_pdb, _args.original_xl, _args.chain_dimer_dict)
    print(th_path)
    print(pred_xl_res_file)


if __name__ == "__main__":
    main()

