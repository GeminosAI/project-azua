"""
Train a model (defaults to PVAE) and optionally evaluate it.

To run:

The simplest way to run is using an existing UCI dataset:
(options: boston, energy, wine, bank) and run
e.g. python run_experiment.py boston

To overwrite hyperparameters, specify model config (-m) or inference config
(-ic) containing values to override.
e.g. python run_experiment.py boston -m parameters/model_config_sweep.json

To run on custom data, you will need to specify the data directory
e.g. python run_experiment.py csv -d data/dataset_name

To see information about other options, run this script with -h.
"""

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from dependency_injector.wiring import Provide, inject


if __name__ == "__main__":
    from azua.experiment.azua_context import AzuaContext
    from azua.experiment.run_aggregation import run_aggregation
    from azua.experiment.run_single_seed_experiment import run_single_seed_experiment, ExperimentArguments
    from azua.utils.configs import get_configs
    from azua.utils.run_utils import find_local_model_dir, create_models_dir
    from azua import models  # type: ignore
    from argument_parser import get_parser, validate_args
else:
    from .azua.experiment.azua_context import AzuaContext
    from .azua.experiment.run_aggregation import run_aggregation
    from .azua.experiment.run_single_seed_experiment import run_single_seed_experiment, ExperimentArguments
    from .azua.utils.configs import get_configs
    from .azua.utils.run_utils import find_local_model_dir, create_models_dir
    from .azua import models
    from .argument_parser import get_parser, validate_args


def split_configs(
    model_config: Dict[str, Any], dataset_config: Dict[str, Any]
) -> List[Tuple[int, Dict[str, Any], Any, Dict[str, Any]]]:
    model_seeds = model_config["random_seed"]
    if not isinstance(model_seeds, list):
        model_seeds = [model_seeds]

    dataset_seeds = dataset_config["random_seed"]
    if not isinstance(dataset_seeds, list):
        dataset_seeds = [dataset_seeds]

    configs = []
    for dataset_seed in dataset_seeds:
        for model_seed in model_seeds:
            new_model_config = model_config.copy()
            new_model_config["random_seed"] = model_seed

            new_dataset_config = dataset_config.copy()
            new_dataset_config["random_seed"] = dataset_seed

            configs.append((model_seed, new_model_config, dataset_seed, new_dataset_config))

    return configs


@inject
def run_experiment(
    dataset_name: str,
    model_config_path: str,
    data_dir: str = "data",
    model_type: str = "pvae",
    model_dir: Optional[str] = None,
    model_id: Optional[str] = None,
    dataset_config_path: Optional[str] = None,
    impute_config_path: Optional[str] = None,
    objective_config_path: Optional[str] = None,
    run_inference: bool = False,
    extra_eval: bool = False,
    active_learning: Optional[List[str]] = None,
    max_steps: int = np.iinfo(np.int64).max,
    max_al_rows: int = np.iinfo(np.int64).max,
    causal_discovery: bool = False,
    treatment_effects: bool = False,
    output_dir: str = "runs",
    device: str = "cpu",
    name: Optional[str] = None,
    quiet: bool = False,
    active_learning_users_to_plot: Optional[List[int]] = None,
    tiny: bool = False,
    random_seed: Optional[int] = None,
    default_configs_dir: Optional[str] = "configs",
    azua_context: AzuaContext = Provide[AzuaContext],
    logger_level: str = "INFO",
    eval_likelihood: bool = True,
):
    if active_learning_users_to_plot is None:
        active_learning_users_to_plot = []
    # Load configs
    model_config, train_hypers, dataset_config, impute_config, objective_config = get_configs(
        model_type=model_type,
        dataset_name=dataset_name,
        override_dataset_path=dataset_config_path,
        override_model_path=model_config_path,
        override_impute_path=impute_config_path,
        override_objective_path=objective_config_path,
        default_configs_dir=default_configs_dir,
    )
    if random_seed is not None:
        model_config["random_seed"] = random_seed
    # Change active learning method if imputation_method is not none and all methods are run
    if active_learning is not None and objective_config["imputation_method"] is not None:
        if active_learning == ["eddi", "rand", "cond_sing", "sing"]:
            active_learning = ["rand_im", "ei", "k_ei", "b_ei", "bin", "gls"]

    # Create directories, record arguments and configs
    try:
        models_dir = create_models_dir(output_dir=output_dir, name=name)
    except FileExistsError:
        # Timestamp has 1-second resolution, causing trouble if we try to run several times in quick succession
        time.sleep(1)
        models_dir = create_models_dir(output_dir=output_dir, name=name)
    experiment_name = f"{dataset_name}.{model_type}" if name is None else name
    metrics_logger = azua_context.metrics_logger()
    aml_tags = {
        "model_type": model_type,
        "dataset_name": dataset_name,
        "model_config_path": model_config_path,
        "dataset_config_path": dataset_config_path,
        "impute_config_path": impute_config_path,
        "objective_config_path": objective_config_path,
        "run_inference": run_inference,
        "active_learning": active_learning,
        "causal_discovery": causal_discovery,
        "treatment_effects": treatment_effects,
        "device": device,
        "run_train": model_id is None,
        "model_config": model_config,
        "dataset_config": dataset_config,
        "train_hypers": train_hypers,
        "impute_config": impute_config,
        "objective_config": objective_config,
    }
    metrics_logger.set_tags(aml_tags)

    # Make many model files with diff seed for each.
    configs = split_configs(model_config, dataset_config)
    metrics_logger.set_tags({"num_samples": len(configs)})

    pipeline = azua_context.pipeline()
    pipeline_creation_mode = pipeline is not None
    if pipeline_creation_mode:
        train_step_outputs: List[Any] = []

    for model_seed, model_config, dataset_seed, dataset_config in configs:
        kwargs_dict = dict(
            dataset_name=dataset_name,
            data_dir=data_dir,
            model_type=model_type,
            model_dir=model_dir,
            model_id=model_id,
            run_inference=run_inference,
            extra_eval=extra_eval,
            active_learning=active_learning,
            max_steps=max_steps,
            max_al_rows=max_al_rows,
            causal_discovery=causal_discovery,
            treatment_effects=treatment_effects,
            device=device,
            quiet=quiet,
            active_learning_users_to_plot=active_learning_users_to_plot,
            tiny=tiny,
            dataset_config=dataset_config,
            dataset_seed=dataset_seed,
            model_config=model_config,
            train_hypers=train_hypers,
            impute_config=impute_config,
            objective_config=objective_config,
            output_dir=models_dir,
            experiment_name=experiment_name,
            model_seed=model_seed,
            aml_tags=aml_tags,
            logger_level=logger_level,
            eval_likelihood=eval_likelihood,
        )

        kwargs_file = azua_context.aml_step(
            (lambda **kwargs: run_single_seed_experiment(ExperimentArguments(**kwargs))), pipeline_creation_mode
        )(**kwargs_dict)

        if pipeline_creation_mode:
            step_ouput = pipeline.add_step(
                script_name="run_experiment_step.py",  # TODO: remove
                arguments=["--step", "single_seed_experiment", "--kwargs", kwargs_file],
                step_name=experiment_name,
                output_dir=f"outputs{len(train_step_outputs)}",  # specifying unique output_dir, see #16728
            )
            train_step_outputs.append(step_ouput)

    # For local runs, temporary logic to extract input dirs given models_dir
    # Going forward (i.e. once we use AML pipeline for local runs),
    # inputs dirs will be explicitly specified (as they are in remote runs)
    input_dirs = [f.path for f in os.scandir(models_dir) if f.is_dir()]

    kwargs_file = azua_context.aml_step(run_aggregation, pipeline_creation_mode)(
        input_dirs=input_dirs, output_dir=models_dir, experiment_name=experiment_name, aml_tags=aml_tags
    )
    if pipeline_creation_mode:
        pipeline.add_step(
            script_name="run_experiment_step.py",  # TODO: remove
            arguments=["--step", "aggregation", "--kwargs", kwargs_file, "--input_dirs"] + train_step_outputs,
            inputs=train_step_outputs,
            step_name=experiment_name,
        )
        pipeline.run(aml_tags)

    # TODO this return value is provided only for the sake of end_to_end tests. Remove it?
    return models_dir


def run_experiment_on_parsed_args(args: argparse.Namespace):

    # Expand args for active learning
    if args.active_learning is not None and "all" in args.active_learning:
        args.active_learning = ["eddi", "rand", "sing"]

    # Get model_dir, model_id from model_dir
    if args.model_dir is not None:
        args.model_dir, args.model_id = find_local_model_dir(args.model_dir)
    else:
        args.model_id = None

    run_experiment(
        dataset_name=args.dataset_name,
        model_config_path=args.model_config,
        data_dir=args.data_dir,
        model_type=args.model_type,
        model_dir=args.model_dir,
        model_id=args.model_id,
        dataset_config_path=args.dataset_config,
        impute_config_path=args.impute_config,
        objective_config_path=args.objective_config,
        run_inference=args.run_inference,
        extra_eval=args.extra_eval,
        active_learning=args.active_learning,
        max_steps=args.max_steps,
        max_al_rows=args.max_al_rows,
        causal_discovery=args.causal_discovery,
        treatment_effects=args.treatment_effects,
        output_dir=args.output_dir,
        device=args.device,
        name=args.name,
        quiet=False,
        active_learning_users_to_plot=args.users_to_plot,
        tiny=args.tiny,
        random_seed=args.random_seed,
        default_configs_dir=args.default_configs_dir,
        logger_level=args.logger_level,
        eval_likelihood=args.eval_likelihood,
    )


def main(user_args):
    parser = get_parser()
    args = parser.parse_args(user_args)
    validate_args(args)

    azua_context = AzuaContext()
    azua_context.wire(modules=[sys.modules[__name__]], packages=[models])
    run_experiment_on_parsed_args(args)


if __name__ == "__main__":
    main(sys.argv[1:])
