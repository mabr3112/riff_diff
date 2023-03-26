#!/home/mabr3112/anaconda3/bin/python3.9
import sys
sys.path.append("/home/mabr3112/riff_diff")
sys.path += ["/home/mabr3112/projects/iterative_refinement/"]
sys.path += ["/home/markus/Desktop/script_development/iterative_refinement/"]

import json
from iterative_refinement import *
from glob import glob
import utils.plotting as plots 
import utils.biopython_tools
import utils.pymol_tools

def write_new_halluc_pose_opts(row: str, opts_col: str, sequence_col: str) -> str:
    '''
    Params:
        sequence_col, str: Column in row that contains location of .fa file
    '''
    #print(row.index)
    #contig_str = row[contig_col]
    #def get_force_aa_from_contig(contig_str: str) -> str:
    #    return ",".join([x for x in contig_str.split(",") if x[0].isalpha()])
    #force_aa = get_force_aa_from_contig(contig_str)
    return row[opts_col] + f" --spike_fas {row[sequence_col]}"

def divide_flanking_residues(residual: int, flanking: str) -> tuple:
    ''''''
    def split_flankers(residual, flanking) -> tuple:
        ''''''
        cterm = residual // 2
        nterm = residual - cterm
        return nterm, cterm
    
    residual = int(residual)
    if residual < 6 or flanking == "split":
        return split_flankers(residual, flanking)
    elif flanking == "nterm":
        return residual-3, 3
    elif flanking == "cterm":
        return 3, residual-3
    else:
        raise ValueError(f"Paramter <flanking> can only be 'split', 'nterm', or 'cterm'. flanking: {flanking}")

def adjust_flanking(hallucinate_pose_opts: str, flanking_type: str, total_flanker_length:int=None) -> str:
    '''AAA'''
    def get_contigs_str(hal_opts: str) -> str:
        return [x for x in hal_opts.split(" --") if x.startswith("--mask")][0].split()[1]
    
    # extract contig from contigs_str
    contig = get_contigs_str(hallucinate_pose_opts)
    
    # extract flankings and middle part
    csplit = contig.split(",")
    og_nterm, middle, og_cterm = int(csplit[0]), ",".join(csplit[1:-1]), int(csplit[-1])
    
    # readjust flankings according to flanking_type and max_pdb_length
    pdb_length = total_flanker_length or og_nterm+og_cterm
    nterm, cterm = divide_flanking_residues(pdb_length, flanking=flanking_type)
    
    # reassemble contig string and replace with hallucinate pose opts.
    reassembled = f"{nterm},{middle},{cterm}"
    return hallucinate_pose_opts.replace(contig, reassembled)

def update_and_copy_reference_frags(input_df: pd.DataFrame, ref_col:str, desc_col:str, motif_prefix: str, out_pdb_path=None) -> list[str]:
    ''''''
    list_of_mappings = [utils.biopython_tools.residue_mapping_from_motif(ref_motif, inp_motif) for ref_motif, inp_motif in zip(input_df[f"{motif_prefix}_con_ref_pdb_idx"].to_list(), input_df[f"{motif_prefix}_con_hal_pdb_idx"].to_list())]
    output_pdb_names_list = [f"{out_pdb_path}/{desc}.pdb" for desc in input_df[desc_col].to_list()]

    list_of_output_paths = [utils.biopython_tools.renumber_pdb_by_residue_mapping(ref_frag, res_mapping, out_pdb_path=pdb_output) for ref_frag, res_mapping, pdb_output in zip(input_df[ref_col].to_list(), list_of_mappings, output_pdb_names_list)]

    return list_of_output_paths

def parse_outfilter_args(scoreterm_str: str, weights_str: str, df: pd.DataFrame) -> tuple[list]:
    ''''''
    def check_for_col_in_df(col: str, datf: pd.DataFrame) -> None:
        if col not in datf.columns: raise KeyError("Scoreterm {col} not found in poses_df. Available scoreterms: {','.join(datf.columns)}")
    scoreterms = scoreterm_str.split(",")
    weights = [float(x) for x in weights_str.split(",")]
    check = [check_for_col_in_df(scoreterm, df) for scoreterm in scoreterms]

    if not len(scoreterms) == len(weights): raise ValueError(f"Length of --output_scoreterms ({scoreterm_str}: {len(scoreterm_str)}) and --output_scoreterm_weights ({weights_str}: {len(weights_str)}) is not the same. Both arguments must be of the same length!")

    return scoreterms, weights

def extract_rosetta_pose_opts(input_data: pd.Series) -> str:
    '''AAA'''
    def collapse_dict_values(in_dict: dict) -> str:
        return ",".join([str(y) for x in in_dict.values() for y in x])
    native_file = f"-in:file:native ref_fragments/{input_data['poses_description']}.pdb"
    script_vars = f"-parser:script_vars motif_res='{collapse_dict_values(input_data['motif_residues'])}' cat_res='{collapse_dict_values(input_data['fixed_residues'])}'"
    return [" ".join([native_file, script_vars])]

def write_rosetta_pose_opts_to_json(input_df: pd.DataFrame, path_to_json_file: str) -> str:
    '''AAA'''
    pose_opts_dict = {input_df.loc[index, "poses_description"]: extract_rosetta_pose_opts(input_df.loc[index]) for index in input_df.index}
    with open(path_to_json_file, 'w') as f:
        json.dump(pose_opts_dict, f)
    return path_to_json_file

def main(args):
    # print Status
    print(f"\n{'#'*50}\nRunning hallucination_ensembles_sampling.py on {args.input_dir}\n{'#'*50}\n")

    # Parse Poses
    pdb_dir = f"{args.input_dir}/pdb_in/"
    ensembles = Poses(args.output_dir, glob(f"{pdb_dir}/*.pdb"))
    ensembles.max_inpaint_gpus = args.max_hallucination_gpus

    # Read scores of selected paths from ensemble_evaluator and store them in poses_df:
    path_df = pd.read_json(f"{args.input_dir}/selected_paths.json").reset_index().rename(columns={"index": "rdescription"})
    ensembles.poses_df = ensembles.poses_df.merge(path_df, left_on="poses_description", right_on="rdescription")
    print(len(ensembles.poses_df))
    
    # properly setup Contigs DataFrame
    motif_cols = ["fixed_residues", "motif_residues"]

    # change cterm and nterm flankers according to input args.
    if args.flanking: ensembles.poses_df["hallucination_pose_opts"] = [adjust_flanking(hal_pose_opts_str, args.flanking, args.total_flanker_length) for hal_pose_opts_str in ensembles.poses_df["hallucination_pose_opts"].to_list()]    
    print(ensembles.poses_df.iloc[0]["hallucination_pose_opts"])

    # Check if merger was successful:
    if len(ensembles.poses_df) == len(ensembles.poses): print(f"Loading of Pose contigs into poses_df successful. Continuing to hallucination.")
    else: raise ValueError(f"Merging of hallucination_opts into poses_df failed! Check if keys in hallucination_opts match with pose_names!!!")

    # store original motifs for calculation of Motif RMSDs later
    ensembles.poses_df["template_motif"] = ensembles.poses_df["motif_residues"]
    ensembles.poses_df["template_fixedres"] = ensembles.poses_df["fixed_residues"]

    # Inpaint, relax and calc pLDDT
    hallucination_options = f"--num {args.num_hallucinations} --use_template=True --w_cce {str(args.w_cce)} --w_rog 1 --rog_thresh {args.rog_thresh} --steps {args.hallucination_steps} --seq_prob_type=soft"
    if args.add_ligand: hallucination_options += f" --w_rep={args.w_rep} --rep_sigma={args.rep_sigma} --rep_pdb {args.input_dir}/ligand/LG1.pdb"
    hallucinations = ensembles.hallucinate(options=hallucination_options, pose_options=list(ensembles.poses_df["hallucination_pose_opts"]), prefix="hallucination")

    # Update motif_res and fixedres to residue mapping after hallucination 
    _ = [ensembles.update_motif_res_mapping(motif_col=col, inpaint_prefix="hallucination") for col in motif_cols]
    _ = ensembles.update_res_identities(identity_col="catres_identities", inpaint_prefix="hallucination")

    # Filter down (first, to one hallucination per backbone, then by half) based on pLDDT and RMSD
    hal_template_rmsd = ensembles.calc_motif_bb_rmsd_dir(ref_pdb_dir=pdb_dir, ref_motif=list(ensembles.poses_df["template_motif"]), target_motif=list(ensembles.poses_df["motif_residues"]), metric_prefix="hallucination_template_bb_ca", remove_layers=1)
    hal_comp_score = ensembles.calc_composite_score("hallucination_comp_score", ["hallucination_loss_cce", "hallucination_loss_kl", "hallucination_template_bb_ca_motif_rmsd"], [1, 1, args.hallucination_rmsd_weight])
    hal_sampling_filter = ensembles.filter_poses_by_score(args.num_mpnn_inputs, "hallucination_comp_score", prefix="hallucination_sampling_filter", remove_layers=1, plot=["hallucination_comp_score", "hallucination_loss_kl", "hallucination_loss_cce", "hallucination_template_bb_ca_motif_rmsd", "hallucination_trf_motif_bb_ca_rmsd"])
    
    # mutate any residues in the pose back to what they are supposed to be (hallucination sometimes does not keep the sequence)
    _ = ensembles.biopython_mutate("catres_identities")

    # Run MPNN and filter (by half)
    mpnn_designs = ensembles.mpnn_design(mpnn_options=f"--num_seq_per_target={args.num_mpnn_seqs} --sampling_temp=0.1", prefix="mpnn", fixed_positions_col="fixed_residues")
    mpnn_seqfilter = ensembles.filter_poses_by_score(args.num_esm_inputs, "mpnn_score", prefix="mpnn_seqfilter", remove_layers=1)

    # Run ESMFold and calc bb_ca_rmsd, motif_ca_rmsd and motif_heavy RMSD
    esm_preds = ensembles.predict_sequences(run_ESMFold, prefix="esm")
    esm_bb_ca_rmsds = ensembles.calc_bb_rmsd_dir(ref_pdb_dir=hallucinations, metric_prefix="esm", ref_chains=["A"], pose_chains=["A"], remove_layers=1)
    esm_motif_rmsds = ensembles.calc_motif_bb_rmsd_dir(ref_pdb_dir=pdb_dir, ref_motif=list(ensembles.poses_df["template_motif"]), target_motif=list(ensembles.poses_df["motif_residues"]), metric_prefix="esm_bb_ca", remove_layers=2)
    esm_motif_heavy_rmsds = ensembles.calc_motif_heavy_rmsd_dir(ref_pdb_dir=pdb_dir, ref_motif=ensembles.poses_df["template_fixedres"].to_list(), target_motif=ensembles.poses_df["fixed_residues"].to_list(), metric_prefix="esm_catres", remove_layers=2)

    # Filter Redesigns based on confidence and RMSDs
    esm_comp_score = ensembles.calc_composite_score("esm_comp_score", ["esm_plddt", "esm_bb_ca_motif_rmsd"], [-1, 1])
    esm_filter = ensembles.filter_poses_by_score(args.num_esm_outputs_per_input_backbone, "esm_comp_score", remove_layers=1, prefix="esm_filter", plot=["esm_comp_score", "esm_plddt", "esm_bb_ca_rmsd", "esm_bb_ca_motif_rmsd", "esm_catres_motif_heavy_rmsd"])
    
    # Plot Results
    if not os.path.isdir((plotdir := f"{ensembles.dir}/plots")): os.makedirs(plotdir, exist_ok=True)

    # Inpainting stats:
    cols = ["hallucination_loss_kl", "hallucination_loss_cce", "hallucination_trf_motif_bb_ca_rmsd", "hallucination_template_bb_ca_motif_rmsd", "mpnn_score"]
    titles = ["Hallucination\nKL-Loss", "Hallucination\nCCE (Motif) Loss", "TRF-Hallucination\nMotif RMSD", "TRF-Template\nMotif RMSD", "MPNN score"]
    y_labels = ["Loss [AU]", "Loss [AU]", "RMSD [\u00C5]", "RMSD [\u00C5]", "-log(prob)"]
    dims = [(0,3), (0,3), (0,2), (0,2), (0,2)]
    _ = plots.violinplot_multiple_cols(ensembles.poses_df, cols=cols, titles=titles, y_labels=y_labels, dims=dims, out_path=f"{plotdir}/hallucination_stats.png")

    # ESM stats:
    cols = ["esm_plddt", "esm_bb_ca_rmsd", "esm_bb_ca_motif_rmsd", "esm_catres_motif_heavy_rmsd"]
    titles = ["ESM pLDDT", "ESM BB-Ca RMSD", "ESM Motif-Ca RMSD", "ESM Catres\nSidechain RMSD"]
    y_labels = ["pLDDT", "RMSD [\u00C5]", "RMSD [\u00C5]", "RMSD [\u00C5]"]
    dims = [(0,100), (0,15), (0,8), (0,8)]
    _ = plots.violinplot_multiple_cols(ensembles.poses_df, cols=cols, titles=titles, y_labels=y_labels, dims=dims, out_path=f"{plotdir}/esm_stats.png")
    # Store filtered poses and scores away:
    ensembles.dump_poses(f"{args.output_dir}/esm_output_pdbs/")

    # Filter down to final set of .pdbs that will be input for Rosetta Refinement:
    scoreterms, weights = parse_outfilter_args(args.output_scoreterms, args.output_scoreterm_weights, ensembles.poses_df)
    out_filterscore = ensembles.calc_composite_score("out_filter_comp_score", scoreterms, weights)
    out_filter = ensembles.filter_poses_by_score(args.num_outputs, f"out_filter_comp_score", prefix="out_filter", plot=scoreterms)
    results_dir = f"{args.output_dir}/results/"
    ref_frag_dir = f"{results_dir}/ref_fragments/"
    if not os.path.isdir(ref_frag_dir): os.makedirs(ref_frag_dir, exist_ok=True)
    ensembles.dump_poses(results_dir)

    # Copy and rewrite Fragments into output_dir/reference_fragments
    updated_ref_pdbs = update_and_copy_reference_frags(ensembles.poses_df, ref_col="input_poses", desc_col="poses_description", motif_prefix="hallucination", out_pdb_path=ref_frag_dir)

    # Write PyMol Alignment Script
    ref_originals = [shutil.copy(ref_pose, f"{results_dir}/") for ref_pose in ensembles.poses_df["input_poses"].to_list()]
    pymol_script = utils.pymol_tools.write_pymol_alignment_script(ensembles.poses_df, scoreterm="out_filter_comp_score", top_n=args.num_outputs, path_to_script=f"{results_dir}/align.pml")

    # Plot final stats of selected poses
    _ = plots.violinplot_multiple_cols(ensembles.poses_df, cols=cols, titles=titles, y_labels=y_labels, dims=dims, out_path=f"{results_dir}/final_esm_stats.png")

    # create pdb_in and stuff:
    # write Rosetta Pose Options to a .json file:
    ros_pose_opts = write_rosetta_pose_opts_to_json(ensembles.poses_df, path_to_json_file=f"{results_dir}/rosetta_pose_opts.json")
    dumped = ensembles.dump_poses(f"{results_dir}/pdb_in/")
    out_df = ensembles.poses_df[["poses_description", "fixed_residues", "motif_residues"]].set_index("poses_description")
    out_df.to_json(f"{results_dir}/motif_res.json")

    ## run second hallucination round:
    ensembles.poses_df["poses"] = ensembles.poses_df["input_poses"] # restore input poses
    ensembles.poses_df["hallucination_pose_opts_round2"] = ensembles.poses_df.apply(write_new_halluc_pose_opts, args=("hallucination_pose_opts", "mpnn_location"), axis=1) # compile new pose_opts
    hal_opts_round2 = f"--num {args.num_hallucinations} --use_template=True --w_cce {str(args.w_cce)} --w_rog 1 --rog_thresh {args.rog_thresh} --steps {args.hallucination_steps_round2} --spike 0.99"
    hal_round2 = ensembles.hallucinate(options=hal_opts_round2, pose_options=ensembles.poses_df["hallucination_pose_opts_round2"].to_list(), prefix="hallucination_v2")
    rmsd_hal_round_2 = ensembles.calc_motif_bb_rmsd_dir(ref_pdb_dir=pdb_dir, ref_motif=ensembles.poses_df["template_motif"].to_list(), target_motif=ensembles.poses_df["motif_residues"].to_list(), metric_prefix="hallucination_v2_template_bb_ca", remove_layers=3)

    # filter for second round of MPNN
    hal_comp_score_r2 = ensembles.calc_composite_score("hallucination_r2_comp_score", ["hallucination_v2_loss_cce", "hallucination_v2_loss_kl", "hallucination_v2_template_bb_ca_motif_rmsd"], [1, 1, args.hallucination_rmsd_weight])
    hal_sampling_filter_r2 = ensembles.filter_poses_by_score(args.num_mpnn_inputs, "hallucination_v2_comp_score", prefix="hallucination_v2_sampling_filter", remove_layers=1, plot=["hallucination_v2_comp_score", "hallucination_v2_loss_kl", "hallucination_v2_loss_cce", "hallucination_v2_template_bb_ca_motif_rmsd", "hallucination_v2_trf_motif_bb_ca_rmsd"])

    # run MPNN
    mpnn_v2 = ensembles.mpnn_design(mpnn_options=f"--num_seq_per_target={args.num_mpnn_seqs} --sampling_temp=0.1", prefix="mpnn_v2", fixed_positions_col="fixed_positions")
    mpnn_seqfilter_v2 = ensembles.filter_poses_by_score(args.num_esm_inputs, "mpnn_v2_score", prefix="mpnn_v2_seqfilter", remove_layers=1)

    # second round of ESMFold
    esm_v2 = ensembles.predict_sequences(run_ESMFold, prefix="esm_v2")
    esm_v2_bb_ca_preds = ensembles.calc_bb_rmsd_dir(ref_pdb_dir=hal_round2, metric_prefix="esm_v2", ref_chains=["A"], pose_chains=["A"], remove_layers=1)
    esm_v2_motif_rmsds = ensembles.calc_motif_bb_rmsd_dir(ref_pdb_dir=pdb_dir, ref_motif=ensembles.poses_df["template_motif"].to_list(), target_motif=ensembles.poses_df["fixed_residues"].to_list(), metric_prefix="esm_v2_catres", remove_layers=2)
    esm_v2_motif_heavy_rmsds = ensembles.calc_motif_heavy_rmsd_dir(ref_pdb_dir=pdb_dir, ref_motif=ensembles.poses_df["template_fixedres"].to_list(), target_motif=ensembles.poses_df["fixed_residues"].to_list(), metric_prefix="esm_v2_catres", remove_layers=2)

    # Filter Redesigns based on confidence and RMSDs:
    esm_v2_comp_score = ensembles.calc_composite_score("esm_v2_comp_score", ["esm_v2_plddt", "esm_v2_bb_ca_motif_rmsd"], [-1, 1])
    esm_v2_filter = ensembles.filter_poses_by_score(args.num_esm_output_per_input_backbone, "esm_v2_comp_score", remove_layers=1, prefix="esm_v2_filter", plot=["esm_v2_comp_score", "esm_v2_plddt", "esm_v2_bb_ca_rmsd", "esm_v2_bb_ca_motif_rmsd", "esm_v2_catres_motif_heavy_rmsd"])

    # Hallucination round 2 stats:
    cols = ["hallucination_v2_loss_kl", "hallucination_v2_loss_cce", "hallucination_v2_trf_motif_bb_ca_rmsd", "hallucination_v2_template_bb_ca_motif_rmsd", "mpnn_v2_score"]
    titles = ["Hallucination\nKL-Loss", "Hallucination\nCCE (Motif) Loss", "TRF-Hallucination\nMotif RMSD", "TRF-Template\nMotif RMSD", "MPNN score"]
    y_labels = ["Loss [AU]", "Loss [AU]", "RMSD [\u00C5]", "RMSD [\u00C5]", "-log(prob)"]
    dims = [(0,-2), (0,3), (0,2), (0,2), (0,2)]
    _ = plots.violinplot_multiple_cols(ensembles.poses_df, cols=cols, titles=titles, y_labels=y_labels, dims=dims, out_path=f"{plotdir}/hallucination_v2_stats.png")

    # ESM round 2 stats:
    cols = ["esm_v2_plddt", "esm_v2_bb_ca_rmsd", "esm_v2_bb_ca_motif_rmsd", "esm_v2_catres_motif_heavy_rmsd"]
    titles = ["ESM pLDDT", "ESM BB-Ca RMSD", "ESM Motif-Ca RMSD", "ESM Catres\nSidechain RMSD"]
    y_labels = ["pLDDT", "RMSD [\u00C5]", "RMSD [\u00C5]", "RMSD [\u00C5]"]
    dims = [(0,100), (0,15), (0,8), (0,8)]
    _ = plots.violinplot_multiple_cols(ensembles.poses_df, cols=cols, titles=titles, y_labels=y_labels, dims=dims, out_path=f"{plotdir}/esm_v2_stats.png")
    # Store filtered poses and scores away:
    ensembles.dump_poses(f"{args.output_dir}/esm_v2_output_pdbs/")
    # Filter down to final set of .pdbs that will be input for Rosetta Refinement:
    scoreterms, weights = parse_outfilter_args(args.final_output_scoreterms, args.final_output_scoreterm_weights, ensembles.poses_df)
    out_filterscore = ensembles.calc_composite_score("out_filter_v2_comp_score", scoreterms, weights)
    out_filter = ensembles.filter_poses_by_score(args.num_outputs, f"out_filter_v2_comp_score", prefix="out_filter_v2", plot=scoreterms)
    results_dir_v2 = f"{args.output_dir}/results_v2/"
    ref_frag_dir_v2 = f"{results_dir}/ref_fragments_v2/"
    if not os.path.isdir(ref_frag_dir_v2): os.makedirs(ref_frag_dir_v2, exist_ok=True)
    ensembles.dump_poses(results_dir_v2)

    # Copy and rewrite Fragments into output_dir/reference_fragments
    updated_ref_pdbs = update_and_copy_reference_frags(ensembles.poses_df, ref_col="input_poses", desc_col="poses_description", motif_prefix="hallucination_v2", out_pdb_path=ref_frag_dir_v2)

    # Write PyMol Alignment Script
    ref_originals = [shutil.copy(ref_pose, f"{results_dir_v2}/") for ref_pose in ensembles.poses_df["input_poses"].to_list()]
    pymol_script = utils.pymol_tools.write_pymol_alignment_script(ensembles.poses_df, scoreterm="out_filter_v2_comp_score", top_n=args.num_outputs, path_to_script=f"{results_dir_v2}/align_v2.pml")

    # Plot final stats of selected poses
    _ = plots.violinplot_multiple_cols(ensembles.poses_df, cols=cols, titles=titles, y_labels=y_labels, dims=dims, out_path=f"{results_dir_v2}/final_esm_stats_v2.png")

    # write Rosetta Pose Options to a .json file:
    ros_pose_opts = write_rosetta_pose_opts_to_json(ensembles.poses_df, path_to_json_file=f"{results_dir_v2}/rosetta_pose_opts.json")
    dumped = ensembles.dump_poses(f"{results_dir_v2}/pdb_in/")
    out_df = ensembles.poses_df[["poses_description", "fixed_residues", "motif_residues"]].set_index("poses_description")
    out_df.to_json(f"{results_dir_v2}/motif_res.json")

    # done
    print("Done")
    


if __name__ == "__main__":
    import argparse

    argparser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    argparser.add_argument("--input_dir", type=str, required=True, help="input_directory that contains all ensemble *.pdb files to be hallucinated (max 1000 files).")
    argparser.add_argument("--output_dir", type=str, required=True, help="output_directory")

    # hallucination options
    argparser.add_argument("--num_hallucinations", type=int, default=5, help="Number of hallucination trajectories.")
    argparser.add_argument("--w_cce", type=float, default=1.25, help="Weight of Cross-Entropy loss for constrained hallucination (Strength of motif loss).")
    argparser.add_argument("--rog_thresh", type=float, default=18, help="Threshold for rog loss (Above this value, the loss starts to count)")
    argparser.add_argument("--hallucination_rmsd_weight", type=float, default=1, help="Weight of hallucination RMSD score for filtering sampled hallucination")
    argparser.add_argument("--max_hallucination_gpus", type=int, default=10, help="On how many GPUs at a time to you want to run Hallucination?")
    argparser.add_argument("--hallucination_steps", type=str, default="g400,m1000", help="Optimization steps for constrained Hallucination.")
    argparser.add_argument("--flanking", type=str, default=None, help="Overwrites contig output of 'run_ensemble_evaluator.py'. Can be either 'split', 'nterm', 'cterm'")
    argparser.add_argument("--total_flanker_length", type=int, default=None, help="Overwrites contig output of 'run_ensemble_evaluator.py'. Set the max length of the pdb-file that is being hallucinated. Will only be used in combination with 'flanking'")
    argparser.add_argument("--add_ligand", type=bool, default=True, help="Do you want to do hallucination with a ligand?")
    argparser.add_argument("--w_rep", type=float, default=1, help="Weight of repulsive loss for hallucination. Only used, if add_ligand is set.")
    argparser.add_argument("--rep_sigma", type=float, default=3.5, help="Interatomic distance for repulsive loss (w_rep) during hallucination. Only used if add_ligand is set.")
    argparser.add_argument("--hallucination_steps_round2", type=str, default="g400,m1000", help="Optimization steps for second round of hallucination")

    # mpnn options
    argparser.add_argument("--num_mpnn_inputs", type=int, default=1, help="Number of hallucinations for each input fragment that should be passed to MPNN.")
    argparser.add_argument("--num_mpnn_seqs", type=int, default=50, help="Number of MPNN Sequences to generate for each input backbone.")
    argparser.add_argument("--num_esm_inputs", type=int, default=10, help="Number of MPNN Sequences for each input backbone that should be predicted. Typically quarter to half of the sequences generated by MPNN is a good value.")

    # output options
    argparser.add_argument("--num_outputs", type=int, default=25, help="Number of .pdb files that will be stored into the final output directory.")
    argparser.add_argument("--output_scoreterms", type=str, default="esm_plddt,esm_bb_ca_motif_rmsd", help="Scoreterms to use to filter ESMFolded PDBs to the final output pdbs. IMPORTANT: if you supply scoreterms, also supply weights and always check the filter output plots in the plots/ directory!")
    argparser.add_argument("--output_scoreterm_weights", type=str, default="-1,1", help="Weights for how to combine the scoreterms listed in '--output_scoreterms'")
    argparser.add_argument("--final_output_scoreterms", type=str, default="esm_v2_plddt,esm_v2_bb_ca_motif_rmsd", help="Scoreterms to use to filter ESMFolded PDBs to the final output pdbs. IMPORTANT: if you supply scoreterms, also supply weights and always check the filter output plots in the plots/ directory!")
    argparser.add_argument("--final_output_scoreterm_weights", type=str, default="-1,1", help="Weights for how to combine the scoreterms listed in '--output_scoreterms'")
    argparser.add_argument("--num_esm_outputs_per_input_backbone", type=int, default=5, help="How many of the 'args.num_esm_inputs' structures should be kept?")

    args = argparser.parse_args()

    main(args)
