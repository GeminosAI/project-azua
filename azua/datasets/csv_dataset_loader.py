import io
import logging
import numpy as np
import pandas as pd
import os
from typing import List, Optional, Tuple, Union, cast
import warnings

from ..datasets.dataset import Dataset
from ..datasets.dataset_loader import DatasetLoader
from ..datasets.variables import Variables

logger = logging.getLogger(__name__)


class CSVDatasetLoader(DatasetLoader):
    """
    Load a dataset from a CSV file in tabular format, i.e. where each row is an individual datapoint and each
    column is a feature.
    """

    _all_data_file = "all.csv"
    _train_data_file = "train.csv"
    _val_data_file = "val.csv"
    _test_data_file = "test.csv"

    def split_data_and_load_dataset(
        self,
        test_frac: float,
        val_frac: float,
        random_state: Union[int, Tuple[int, int]],
        max_num_rows: Optional[int] = None,
        negative_sample: bool = False,
        **kwargs,
    ) -> Dataset:
        """
        Load the data from disk and make the train/val/test split to instantiate a dataset.
        The data is split deterministically given the random state. If the given random state is a pair of integers,
        the first is used to extract test set and the second is used to extract the validation set from the remaining data.
        If only a single integer is given as random state it is used for both.
        Args:
            test_frac: Fraction of data to put in the test set.
            val_frac: Fraction of data to put in the validation set.
            random_state: An integer or a tuple of integers to be used as the splitting random state.
            max_num_rows: Maximum number of rows to include when reading data files.
            negative_sample: Whether to perform negative sampling after loading the dataset. Negative sampling requires
                a file negative_sampling_levels.csv in the dataset folder, and negative samples for each row will be 
                drawn from features of a greater level than all those observed in the row.
        Returns:
            dataset: Dataset object, holding the data and variable metadata.
        """
        logger.info(f"Splitting data to load the dataset: test fraction: {test_frac}, validation fraction: {val_frac}.")

        data_path = os.path.join(self._dataset_dir, self._all_data_file)
        self._download_data_if_necessary(self._dataset_dir)

        if not os.path.exists(data_path):
            raise FileNotFoundError(f"The required data file not found: {data_path}.")

        data, mask = self.read_csv_from_file(data_path, max_num_rows=max_num_rows)

        num_rows, _ = data.shape
        rows = list(range(num_rows))
        train_rows, val_rows, test_rows, data_split = self._generate_data_split(rows, test_frac, val_frac, random_state)

        train_data = data[train_rows, :]
        train_mask = mask[train_rows, :]
        test_data = data[test_rows, :]
        test_mask = mask[test_rows, :]

        if len(val_rows) == 0:
            val_data, val_mask = None, None
        else:
            val_data = data[val_rows, :]
            val_mask = mask[val_rows, :]

        variables_dict = self._load_variables_dict()
        variables = Variables.create_from_data_and_dict(train_data, train_mask, variables_dict)

        if negative_sample:
            train_data, train_mask, val_data, val_mask, test_data, test_mask = self._apply_negative_sampling(
                variables, train_data, train_mask, val_data, val_mask, test_data, test_mask
            )

        return Dataset(
            train_data=train_data,
            train_mask=train_mask,
            val_data=val_data,
            val_mask=val_mask,
            test_data=test_data,
            test_mask=test_mask,
            variables=variables,
            data_split=data_split,
        )

    def load_predefined_dataset(
        self, max_num_rows: Optional[int] = None, negative_sample: bool = False, **kwargs
    ) -> Dataset:
        """
        Load the data from disk and use the predefined train/val/test split to instantiate a dataset.
        Args:
            max_num_rows: Maximum number of rows to include when reading data files.
            negative_sample: Whether to perform negative sampling after loading the dataset. Negative sampling requires
                a file negative_sampling_levels.csv in the dataset folder, and negative samples for each row will be 
                drawn from features of a greater level than all those observed in the row.
        Returns:
            dataset: Dataset object, holding the data and variable metadata.
        """
        logger.info("Using a predefined data split to load the dataset.")

        # Download data
        train_data_path = os.path.join(self._dataset_dir, self._train_data_file)
        test_data_path = os.path.join(self._dataset_dir, self._test_data_file)
        val_data_path = os.path.join(self._dataset_dir, self._val_data_file)
        self._download_data_if_necessary(self._dataset_dir)

        # Loading train and test data - raise an error if not found
        train_test_files_exist = all([os.path.exists(train_data_path), os.path.exists(test_data_path)])
        if not train_test_files_exist:
            raise FileNotFoundError(
                f"At least one of the required data files not found: {[train_data_path, test_data_path]}."
            )
        train_data, train_mask = self.read_csv_from_file(train_data_path, max_num_rows=max_num_rows)
        test_data, test_mask = self.read_csv_from_file(test_data_path, max_num_rows=max_num_rows)

        # Loading val data - make a warning if not found
        if not os.path.exists(val_data_path):
            val_data, val_mask = None, None
            warnings.warn(f"Validation data file not found: {val_data_path}.", UserWarning)
        else:
            val_data, val_mask = self.read_csv_from_file(val_data_path, max_num_rows=max_num_rows)

        variables_dict = self._load_variables_dict()
        variables = Variables.create_from_data_and_dict(train_data, train_mask, variables_dict)

        if negative_sample:
            train_data, train_mask, val_data, val_mask, test_data, test_mask = self._apply_negative_sampling(
                variables, train_data, train_mask, val_data, val_mask, test_data, test_mask
            )

        return Dataset(
            train_data=train_data,
            train_mask=train_mask,
            val_data=val_data,
            val_mask=val_mask,
            test_data=test_data,
            test_mask=test_mask,
            variables=variables,
            data_split=self._predefined_data_split,
        )

    @classmethod
    def read_csv_from_file(cls, path: str, max_num_rows: Optional[int] = None) -> Tuple[np.ndarray, np.ndarray]:
        """
        Read the CSV file to generate a data array and the corresponding mask.

        Args:
            path: CSV data file path.
            max_num_rows: Maximum number of rows to include.

        Returns:
            data: Data with missing values replaced by zeros.
            mask: Corresponding mask, where observed values are 1 and unobserved values are 0.
        """
        data = pd.read_csv(path, header=None, nrows=max_num_rows).to_numpy()
        return cls._process_data(data)

    @classmethod
    def read_csv_from_strings(cls, strings: List[str]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Read the list of input strings to generate a data array and the corresponding mask.

        Args:
            strings: List of strings, where each string is one data row expressed in a comma separated format.
                e.g. ",,2,,3,4,"

        Returns:
            data: Data with missing values replaced by zeros.
            mask: Corresponding mask, where observed values are 1 and unobserved values are 0.
        """
        strings_csv_buffer = io.StringIO("\n".join(strings))
        data = pd.read_csv(strings_csv_buffer, header=None, index_col=None).to_numpy()
        return cls._process_data(data)

    @classmethod
    def _process_data(cls, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Replace missing values with zeros(/empty strings) and generate the corresponding mask.

        Args:
            data: Data with missing values (either floats or strings)

        Returns:
            data: Data with missing values replaced by zeros(/empty strings).
            mask: Corresponding mask, where observed values are 1 and unobserved values are 0.
        """

        v_is_value_present = np.vectorize(cls._is_value_present)
        mask = cast(np.ndarray, v_is_value_present(data))

        def convert_nan_value(single_value):
            if isinstance(single_value, str):
                return single_value
            else:
                return np.nan_to_num(single_value, copy=False)

        v_convert_nan_value = np.vectorize(convert_nan_value, otypes=[object])
        data = v_convert_nan_value(data)
        return data, mask

    @classmethod
    def _is_value_present(cls, single_value: object):
        """
            Check whether the value is present (i.e. not missing)
        """
        if isinstance(single_value, str):
            return single_value != ""
        else:
            # TODO: do right cast for np.isnan
            return ~np.isnan(single_value)  # type: ignore
