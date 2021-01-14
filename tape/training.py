from argparse import ArgumentParser, Namespace
import sys
import logging
from tape import tasks
from tape.models.modeling_utils import ProteinModel

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%y/%m/%d %H:%M:%S"
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)


def get_num_gpus(args: Namespace) -> int:
    try:
        return int(args.gpus)
    except ValueError:
        return sum(1 for gpu in args.gpus.split(",") if gpu)


def maybe_unset_distributed(args: Namespace) -> None:
    if get_num_gpus(args) <= 1:
        args.distributed_backend = None


def train(base_model: ProteinModel):
    import pytorch_lightning as pl

    # Initialize parser
    parser = ArgumentParser()
    parser.add_argument(
        "task",
        choices=["secondary_structure", "fluorescence"],
        help="Which downstream task to train.",
    )
    parser.add_argument(
        "--wandb_project",
        type=str,
        default=None,
        help="Optional wandb project to log to.",
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=3,
        help="Early stopping patience.",
    )
    parser = pl.Trainer.add_argparse_args(parser)
    parser.set_defaults(
        gpus=1,
        min_steps=50,
        max_steps=50000,
        distributed_backend="ddp",
    )

    task = tasks.get(parser)
    task.add_args(parser)

    args = parser.parse_args()
    maybe_unset_distributed(args)
    task_data = task.build_data(args)
    task_model = task.build_model(args, base_model)

    kwargs = {}
    if args.wandb_project:
        try:
            # Requires wandb to be installed
            logger = pl.loggers.WandbLogger(project=args.wandb_project)
            logger.log_hyperparams(args)
            kwargs["logger"] = logger
        except ImportError:
            raise ImportError(
                "Cannot use W&B logger w/o W&b install. Run `pip install wandb` first."
            )
    checkpoint_callback = pl.callbacks.ModelCheckpoint(
        monitor="loss/valid",
    )
    early_stopping_callback = pl.callbacks.EarlyStopping(
        monitor="loss/valid",
        patience=args.patience,
    )
    # Initialize Trainer
    trainer = pl.Trainer.from_argparse_args(
        args,
        checkpoint_callback=checkpoint_callback,
        callbacks=[early_stopping_callback],
        **kwargs
    )
    trainer.fit(task_model, datamodule=task_data)


if __name__ == "__main__":
    from tape.models.modeling_bert import ProteinBertModel
    base_model = ProteinBertModel.from_pretrained("bert-base")
    train(base_model)
