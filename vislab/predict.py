"""
Possible experiments:

- Flickr style, binary
- Flickr style, OAA
- PASCAL, binary
- PASCAL, OAA
- Wikipaintings style, binary
- Wikipaintings style, OAA
- AVA rating_mean, binary
- AVA rating_std, binary
- AVA rating_mean 3-way, OAA
- AVA style, binary
- AVA style, OAA
"""
import pandas as pd
import numpy as np
import vislab.utils.cmdline
import vislab.dataset


def get_multiclass_dataset(
        source_df, dataset_name, column_labels, test_frac=.2,
        random_seed=42):
    pass
    # TODO
    # main gotcha here is when multiple labels are on.
    # solution is probably to replicate the example with less weight


def _process_df_for_regression(df, test_frac):
    N = df.shape[0]
    num_test = int(test_frac * N)
    num_val = num_test

    ind = np.random.permutation(N)
    test_ids = df.index[ind[:num_test]]
    val_ids = df.index[ind[num_test:num_test + num_val]]
    train_ids = df.index[ind[num_test + num_val:]]

    return df, train_ids, test_ids, val_ids


def _process_df_for_binary_clf(df, test_frac, min_pos_frac):
    # The total number is the number of + examples.
    num_total = df['label'].sum()
    num_test = int(test_frac * num_total)
    num_val = num_test

    # Take equal number + and - examples for the test and val sets.
    ind = np.random.permutation(num_total)
    test_ids = np.concatenate((
        df[df['label']].index[ind[:num_test]],
        df[~df['label']].index[ind[:num_test]]
    ))

    val_ids = np.concatenate((
        df[df['label']].index[ind[num_test:num_test + num_val]],
        df[~df['label']].index[ind[num_test:num_test + num_val]]
    ))

    # At first, take all other examples for the training set.
    train_ids = df.index.diff(test_ids.tolist() + val_ids.tolist())

    # But to respect min_pos_frac, have to subsample negative examples.
    train_df = df.ix[train_ids]
    max_num = 1. / min_pos_frac * train_df['label'].sum()
    train_ids = np.concatenate((
        train_df[train_df['label']].index,
        train_df[~train_df['label']].index[:max_num]
    ))

    # Add the remaining ids to the test set, to ensure that all images
    # in the dataset are classified.
    remaining_ids = df.index.diff(
        test_ids.tolist() + val_ids.tolist() + train_ids.tolist())
    test_ids = np.concatenate((test_ids, remaining_ids))

    # Convert to +1/-1 labels.
    labels = np.ones(df.shape[0])
    labels[~df['label']] = -1
    df['label'] = labels
    df = df[['label']]

    return df, train_ids, val_ids, test_ids


def get_binary_or_regression_dataset(
        source_df, dataset_name, column_name, test_frac=.2, min_pos_frac=.1,
        random_seed=42):
    """
    Output a dataset dict suitable for the prediction code of binary
    or regression data in column_name column of source_df.
    Whether the data is binary or regression is inferred from dtype.

    # NOTE: assumes that negative data is more prevalent than pos.

    # TODO: add ability to pass a filter to use for the AVA delta stuff

    Parameters
    ----------
    source_df: pandas.DataFrame
    dataset_name: string
    column_name: string
    test_frac: float
        Use this fraction of the positive examples to test.
        Will use the same amount for validation.
    min_pos_frac: float
        Subsample negative data s.t. pos/neg ratio is at least this.
        Only relevant if the data is binary, obviously.
    random_seed: int [42]
    """
    np.random.seed(random_seed)

    df = pd.DataFrame(
        {'label': source_df[column_name]}, source_df.index)

    # Establish whether the data is for binary or regression,
    # and split the dataset into train/val/test appropriately.
    if df['label'].dtype == bool or df['label'].nunique() == 2:
        task = 'clf'
        num_labels = 2
        df, train_ids, val_ids, test_ids = _process_df_for_binary_clf(
            df, test_frac, min_pos_frac)

    elif df['label'].dtype == float:
        task = 'regr'
        num_labels = -1
        df, train_ids, val_ids, test_ids = _process_df_for_regression(
            df, test_frac, min_pos_frac)

    else:
        raise Exception("Can only deal with binary or float values.")

    # Get the train/val/test datasets.
    def get_split_df(ids):
        split_df = df.ix[ids]
        split_df['importance'] = _get_importance(split_df)
        return split_df

    dataset = {
        'train_df': get_split_df(train_ids),
        'val_df': get_split_df(val_ids),
        'test_df': get_split_df(test_ids)
    }

    # Add all relevant info to the data dict to return.
    dataset.update({
        'dataset_name': dataset_name,
        'name': '{}_{}_train_{}'.format(
            dataset_name, column_name, dataset['train_df'].shape[0]),
        'task': task,
        'num_labels': num_labels,
        'salient_parts': {
            'data': '{}_{}'.format(dataset_name, column_name),
            'num_train': dataset['train_df'].shape[0],
            'num_val': dataset['val_df'].shape[0],
            'num_test': dataset['test_df'].shape[0]
        }
    })

    return dataset


def _get_importance(df):
    """
    Get importance weights of data points. The most frequent label gets
    weight < 1, in proportion to its prevalence.

    Parameters
    ----------
    df: pandas.DataFrame
        Must have column 'label'

    Returns
    -------
    importances: pandas.Series
    """
    # TODO: can be replaced by pandas method value_counts()
    counts = [(df['label'] == label).sum() for label in df['label'].unique()]
    mfl = df['label'].unique()[np.argmax(counts)]

    importances = np.ones(df.shape[0])
    ind = (df['label'] == mfl)
    importances[ind] = 1. * (~ind).sum() / ind.sum()

    importances = pd.Series(importances, df.index)
    return importances


def get_prediction_dataset_with_args(args):
    """
    args should contain:
        prediction_label: string
            Can contain a prefix followed by a wildcard *: "style_*".
            In that case, all columns starting with prefix are matched.
    """
    df = vislab.dataset.get_df_with_args(args)

    # If we are matching multiple columns, then we need to construct
    # a multi-class dataset.
    if '*' in args.prediction_label:
        prefix = args.prediction_label.split('*')[0]
        label_cols = [col for col in df.columns if col.startswith(prefix)]
        get_multiclass_dataset(df, label_cols, args)

    # Otherwise, we are matching either a binary or regression label.
    else:
        dataset = get_binary_or_regression_dataset(
            df, args.dataset, args.prediction_label,
            args.test_frac, args.min_pos_frac, args.random_seed)

    return dataset


def predict(args=None):
    if args is None:
        args = vislab.utils.cmdline.get_args(
            __file__, 'predict',
            ['dataset', 'prediction', 'processing', 'feature'])

    # Get the dataset as specified in args.
    dataset = get_prediction_dataset_with_args(args)

    # If we're doing regression, set the loss function appropriately.
    if dataset['task'] == 'regr':
        loss_functions = ['squared']
    else:
        loss_functions = ['logistic']

    # Set the number of passes. Less passes for quadratic features.
    n_train = dataset['train_df'].shape[0]

    # Rule of thumb: 3M examples.
    n_iter = max(2, min(int(np.ceil(3e6 / n_train)), 180))
    num_passes = sorted(set([n_iter / 3, n_iter]))
    if args.quadratic:
        num_passes = sorted(set([2, n_iter / 4]))

    quadratic = 'all' if args.quadratic else ''

    vislab.vw.train_and_test(
        args.collection_name, dataset, args.features,
        force=args.force_predict, num_workers=args.num_workers,
        num_passes=num_passes,
        loss=loss_functions,
        l1_weight=[0],  # , 1e-5, 1e-7],
        l2_weight=[0],  # , 1e-5, 1e-7],
        quadratic=quadratic)


if __name__ == '__main__':
    possible_functions = {
        'predict': predict
    }
    print __file__
    vislab.utils.cmdline.run_function_in_file(__file__, possible_functions)
