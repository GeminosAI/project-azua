# This is required in python 3 to allow return types of the same class.
from __future__ import annotations

import torch
from .end2end_causal import End2endCausal

from typing import Dict, Any, Union, TypeVar, Type
from ...datasets.variables import Variables


from ...baselines.pc import PC
from ..do_why import DoWhy

T = TypeVar("T", bound="PCDoWhy")


class PCDoWhy(End2endCausal):
    """
    Wrapper class for PC discovery + dowhy inference
    """

    def __init__(self, model_id: str, variables: Variables, save_dir: str, device: torch.device, **model_config_dict):
        """
            model_id: Unique model ID for referencing this model instance.
            variables: Information about variables/features used by this model.
            save_dir: Location to save any information about this model, including training data. This wrapper is stateless but this information is needed for test result saving purposes.
            device: device on which DECI will be run. 
            model_config_dict: nested dictionary containing extra arguments for both DECI and DoWhy
        """

        self.discovery_config, self.inference_config = self._split_configs(model_config_dict)
        discovery_model = PC(model_id, variables, save_dir, device, **self.discovery_config)
        inference_model = DoWhy(model_id, variables, save_dir, **self.inference_config)
        super().__init__(
            model_id=model_id,
            variables=variables,
            save_dir=save_dir,
            discovery_model=discovery_model,
            inference_model=inference_model,
            **model_config_dict
        )

    # TODO: remove this method, use parent's implementation and change parent's implementation to create object of class it was called on by using relfection
    @classmethod
    def create(
        cls: Type[T],
        model_id: str,
        save_dir: str,
        variables: Variables,
        model_config_dict: Dict[str, Any],
        device: Union[str, int, torch.device],
    ) -> T:
        """
        Create a new instance of a model with given type.

        Args:
            model_id: Unique model ID for referencing this model instance.
            save_dir: Location to save all model information to.
            variables: Information about variables/features used
                by this model.
            model_config_dict: Any other parameters needed by a specific concrete class. Of
                the form {arg_name: arg_value}. e.g. {"embedding_dim": 10, "latent_dim": 20}
            device: Name of device to load the model on. Valid options are 'cpu', 'gpu', or a device ID
                (e.g. 0 or 1 on a two-GPU machine). Can also pass a torch.device directly. Ignored for some models.
        
        Returns:
            model: Instance of concrete implementation of `Model` class.
        """
        return super().create(
            model_id=model_id,
            save_dir=save_dir,
            variables=variables,
            model_config_dict=model_config_dict,
            device=device,
        )

    @classmethod
    def name(cls) -> str:
        return "pc_dowhy"
