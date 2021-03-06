import logging
import logging.config
import shutil
import os
from io import StringIO
from crawler.helpers import current_time
from unittest.mock import patch
from csv import DictReader
import pytest
from datetime import (
    datetime,
    timezone,
)
from bson.objectid import ObjectId

from tempfile import mkstemp

from crawler.file_processing import (
    Centre,
    CentreFile,
    CentreFileState,
    SUCCESSES_DIR,
    ERRORS_DIR
)
from crawler.constants import (
    COLLECTION_CENTRES,
    COLLECTION_IMPORTS,
    COLLECTION_SAMPLES,
    COLLECTION_SAMPLES_HISTORY,
    FIELD_ROOT_SAMPLE_ID,
    FIELD_RNA_ID,
    FIELD_RESULT,
    FIELD_DATE_TESTED,
    FIELD_LAB_ID,
    FIELD_VIRAL_PREP_ID,
    FIELD_RNA_PCR_ID,
    FIELD_PLATE_BARCODE,
    FIELD_COORDINATE,
    FIELD_SOURCE,
    FIELD_CREATED_AT,
    FIELD_UPDATED_AT,
    MLWH_TABLE_NAME,
    MLWH_TABLE_NAME,
    MLWH_MONGODB_ID,
    MLWH_ROOT_SAMPLE_ID,
    MLWH_RNA_ID,
    MLWH_PLATE_BARCODE,
    MLWH_COORDINATE,
    MLWH_RESULT,
    MLWH_DATE_TESTED_STRING,
    MLWH_DATE_TESTED,
    MLWH_SOURCE,
    MLWH_LAB_ID,
    MLWH_CREATED_AT,
    MLWH_UPDATED_AT
)
from crawler.db import get_mongo_collection


# ----- tests for class Centre -----

def test_get_download_dir(config):
    for centre_config in config.CENTRES:
        centre = Centre(config, centre_config)

        assert centre.get_download_dir() == f"{config.DIR_DOWNLOADED_DATA}{centre_config['prefix']}/"

def test_process_files(mongo_database, config, testing_files_for_process, testing_centres):
    _, mongo_database = mongo_database
    logger = logging.getLogger(__name__)

    centre_config = config.CENTRES[0]
    centre_config["sftp_root_read"] = "tmp/files"
    centre = Centre(config, centre_config)
    centre.process_files()

    imports_collection = get_mongo_collection(mongo_database, COLLECTION_IMPORTS)
    samples_collection = get_mongo_collection(mongo_database, COLLECTION_SAMPLES)
    samples_history_collection = get_mongo_collection(mongo_database, COLLECTION_SAMPLES_HISTORY)

    # # We record *all* our samples
    assert samples_collection.count_documents({"RNA ID": "123_B09", "source": "Alderley"}) == 1



# ----- tests for class CentreFile -----

# tests for checksums
def create_checksum_files_for(filepath, filename, checksums, timestamp):
    list_files = []
    for checksum in checksums:
        full_filename = f"{filepath}/{timestamp}_{filename}_{checksum}"
        file = open(full_filename, "w")
        file.write("Your text goes here")
        file.close()
        list_files.append(full_filename)
    return list_files

def test_checksum_not_match(config, tmpdir):
    with patch.dict(config.CENTRES[0], {"backups_folder": tmpdir.realpath()}):
        tmpdir.mkdir("successes")

        list_files = create_checksum_files_for(
            f"{config.CENTRES[0]['backups_folder']}/successes/",
            "AP_sanger_report_200503_2338.csv",
            ["adfsadf", "asdf"],
            "200601_1414",
        )

        try:
            centre = Centre(config, config.CENTRES[0])
            centre_file = CentreFile("AP_sanger_report_200503_2338.csv", centre)

            assert centre_file.checksum_match("successes") == False
        finally:
            for tmpfile_for_list in list_files:
                os.remove(tmpfile_for_list)

def test_checksum_match(config, tmpdir):
    with patch.dict(config.CENTRES[0], {"backups_folder": tmpdir.realpath()}):

        tmpdir.mkdir("successes")

        list_files = create_checksum_files_for(
            f"{config.CENTRES[0]['backups_folder']}/successes/",
            "AP_sanger_report_200503_2338.csv",
            ["adfsadf", "5c11524df6fd623ae3d687d66152be28"],
            "200601_1414",
        )

        try:
            centre = Centre(config, config.CENTRES[0])
            centre_file = CentreFile("AP_sanger_report_200503_2338.csv", centre)
            assert centre_file.checksum_match("successes") == True
        finally:
            for tmpfile_for_list in list_files:
                os.remove(tmpfile_for_list)

# tests for validating row structure
def test_row_invalid_structure(config):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some file", centre)

    # Not maching regexp
    assert not centre_file.row_valid_structure(
        {"Root Sample ID": "asdf", "Result": "Positive", "RNA ID": "", "Date tested": "adsf"}, 6
    ), "No RNA id"

    assert not centre_file.row_valid_structure(
        {"Root Sample ID": "asdf", "Result": "", "RNA ID": "", "Date Tested": "date"}, 1
    ), "Not barcode"

    # All required but all empty
    assert not centre_file.row_valid_structure(
        {"Root Sample ID": "", "Result": "", "RNA ID": "", "Date tested": ""}, 4
    ), "All are empty"

def test_row_valid_structure(config):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some file", centre)

    assert centre_file.row_valid_structure(
        {"Root Sample ID": "asdf", "Result": "asdf", "RNA ID": "ASDF_A01", "Date tested": "asdf"}, 5
    )

    assert not (
        centre_file.row_valid_structure(
            {"Root Sample ID": "asdf", "Result": "", "RNA ID": "ASDF_A01", "Date tested": ""}, 5
        )
    )

    assert not (
        centre_file.row_valid_structure(
            {"Root Sample ID": "asdf", "Result": "Positive", "RNA ID": "", "Date tested": ""}, 5
        )
    )

# tests for extracting fields
def test_extract_fields(config):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some file", centre)

    barcode_field = "RNA ID"
    barcode_regex = r"^(.*)_([A-Z]\d\d)$"
    assert centre_file.extract_fields(
        {"RNA ID": "ABC123_H01"}, 0, barcode_field, barcode_regex
    ) == ("ABC123", "H01",)
    assert centre_file.extract_fields(
        {"RNA ID": "ABC123_A00"}, 0, barcode_field, barcode_regex
    ) == ("ABC123", "A00",)
    assert centre_file.extract_fields({"RNA ID": "ABC123_H0"}, 0, barcode_field, barcode_regex) == (
        "",
        "",
    )
    assert centre_file.extract_fields({"RNA ID": "ABC123H0"}, 0, barcode_field, barcode_regex) == (
        "",
        "",
    )
    assert centre_file.extract_fields({"RNA ID": "AB23_H01"}, 0, barcode_field, barcode_regex) == (
        "AB23",
        "H01",
    )

# tests for formatting and filtering rows
def test_format_and_filter_rows(config):
    timestamp = "some timestamp"
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some file", centre)
    with patch.object(centre_file, "get_now_timestamp", return_value=timestamp):
        extra_fields_added = [
            {
                "Root Sample ID": "1",
                "RNA ID": "RNA_0043_H09",
                "plate_barcode": "RNA_0043",
                "source": "Alderley",
                "coordinate": "H09",
                "line_number": 2,
                "Result": "Positive",
                "file_name": "some file",
                "file_name_date": None,
                "created_at": timestamp,
                "updated_at": timestamp,
                "Lab ID": None,
            }
        ]

        with StringIO() as fake_csv:
            fake_csv.write("Root Sample ID,RNA ID,Result,Lab ID\n")
            fake_csv.write("1,RNA_0043_H09,Positive\n")
            fake_csv.seek(0)

            csv_to_test_reader = DictReader(fake_csv)

            augmented_data = centre_file.format_and_filter_rows(csv_to_test_reader)
            assert augmented_data == extra_fields_added
            assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 0

        wrong_barcode = [
            {
                "Root Sample ID": "1",
                "RNA ID": "RNA_0043_",
                "Result": "",
                "plate_barcode": "",
                "source": "Alderley",
                "coordinate": "",
                "Lab ID": "",
            }
        ]

        with StringIO() as fake_csv:
            fake_csv.write("Root Sample ID,RNA ID,Result,Lab ID\n")
            fake_csv.write("1,RNA_0043_,Positive\n")
            fake_csv.seek(0)

            csv_to_test_reader = DictReader(fake_csv)

            augmented_data = centre_file.format_and_filter_rows(csv_to_test_reader)
            assert augmented_data == []

            assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 1
            assert centre_file.logging_collection.aggregator_types["TYPE 9"].count_errors == 1

def test_filtered_row_with_extra_columns(config):
    # check have removed extra columns and created a warning error log
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some_file.csv", centre)

    with StringIO() as fake_csv_with_extra_columns:
        fake_csv_with_extra_columns.write(
            f"{FIELD_ROOT_SAMPLE_ID},{FIELD_RNA_ID},{FIELD_RESULT},{FIELD_DATE_TESTED},{FIELD_LAB_ID},extra_col_1,extra_col_2,extra_col_3\n"
        )
        fake_csv_with_extra_columns.write(
            "1,RNA_0043,Positive,today,AP,extra_value_1,extra_value_2,extra_value_3\n"
        )
        fake_csv_with_extra_columns.seek(0)

        csv_to_test_reader = DictReader(fake_csv_with_extra_columns)

        expected_row = {
            "Root Sample ID": "1",
            "RNA ID": "RNA_0043",
            "Result": "Positive",
            "Date Tested": "today",
            "Lab ID": "AP",
        }

        assert centre_file.filtered_row(next(csv_to_test_reader), 2) == expected_row
        assert centre_file.logging_collection.aggregator_types["TYPE 13"].count_errors == 1
        assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 0

def test_filtered_row_with_blank_lab_id(config):
    # check when flag set in config it adds default lab id
    try:
        config.ADD_LAB_ID = True
        centre = Centre(config, config.CENTRES[0])
        centre_file = CentreFile("some_file.csv", centre)

        with StringIO() as fake_csv_without_lab_id:
            fake_csv_without_lab_id.write(
                f"{FIELD_ROOT_SAMPLE_ID},{FIELD_RNA_ID},{FIELD_RESULT},{FIELD_DATE_TESTED}\n"
            )
            fake_csv_without_lab_id.write("1,RNA_0043,Positive,today\n")
            fake_csv_without_lab_id.seek(0)

            csv_to_test_reader = DictReader(fake_csv_without_lab_id)

            expected_row = {
                "Root Sample ID": "1",
                "RNA ID": "RNA_0043",
                "Result": "Positive",
                "Date Tested": "today",
                "Lab ID": "AP",
            }

            assert centre_file.filtered_row(next(csv_to_test_reader), 2) == expected_row
            assert centre_file.logging_collection.aggregator_types["TYPE 12"].count_errors == 1
            assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 1
    finally:
        config.ADD_LAB_ID = False

def test_filtered_row_with_lab_id_present(config):
    # check when flag set in config it adds default lab id
    try:
        config.ADD_LAB_ID = True
        centre = Centre(config, config.CENTRES[0])
        centre_file = CentreFile("some_file.csv", centre)

        with StringIO() as fake_csv_without_lab_id:
            fake_csv_without_lab_id.write(
                f"{FIELD_ROOT_SAMPLE_ID},{FIELD_RNA_ID},{FIELD_RESULT},{FIELD_DATE_TESTED},{FIELD_LAB_ID}\n"
            )
            fake_csv_without_lab_id.write("1,RNA_0043,Positive,today,RealLabID\n")
            fake_csv_without_lab_id.seek(0)

            csv_to_test_reader = DictReader(fake_csv_without_lab_id)

            expected_row = {
                "Root Sample ID": "1",
                "RNA ID": "RNA_0043",
                "Result": "Positive",
                "Date Tested": "today",
                "Lab ID": "RealLabID",
            }

            assert centre_file.filtered_row(next(csv_to_test_reader), 2) == expected_row
            assert centre_file.logging_collection.aggregator_types["TYPE 12"].count_errors == 0
            assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 0
    finally:
        config.ADD_LAB_ID = False

def test_format_and_filter_rows_parsing_filename(config):
    timestamp = "some timestamp"
    # with patch("crawler.file_processing.get_now_timestamp", return_value=timestamp):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("ASDF_200507_1340.csv", centre)
    with patch.object(centre_file, "get_now_timestamp", return_value=timestamp):

        extra_fields_added = [
            {
                "Root Sample ID": "1",
                "RNA ID": "RNA_0043_H09",
                "plate_barcode": "RNA_0043",
                "source": "Alderley",
                "coordinate": "H09",
                "line_number": 2,
                "file_name": "ASDF_200507_1340.csv",
                "file_name_date": datetime(2020, 5, 7, 13, 40),
                "created_at": timestamp,
                "updated_at": timestamp,
                "Result": "Positive",
                "Lab ID": None,
            },
            {
                "Root Sample ID": "2",
                "RNA ID": "RNA_0043_B08",
                "plate_barcode": "RNA_0043",
                "source": "Alderley",
                "coordinate": "B08",
                "line_number": 3,
                "file_name": "ASDF_200507_1340.csv",
                "file_name_date": datetime(2020, 5, 7, 13, 40),
                "created_at": timestamp,
                "updated_at": timestamp,
                "Result": "Negative",
                "Lab ID": None,
            },
        ]

        with StringIO() as fake_csv:
            fake_csv.write("Root Sample ID,RNA ID,Result,Lab ID\n")
            fake_csv.write("1,RNA_0043_H09,Positive\n")
            fake_csv.write("2,RNA_0043_B08,Negative\n")
            fake_csv.seek(0)

            csv_to_test_reader = DictReader(fake_csv)

            augmented_data = centre_file.format_and_filter_rows(csv_to_test_reader)

            assert augmented_data == extra_fields_added
            assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 0

def test_format_and_filter_rows_detects_duplicates(config):
    timestamp = "some timestamp"
    # with patch("crawler.file_processing.get_now_timestamp", return_value=timestamp):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("ASDF_200507_1340.csv", centre)
    with patch.object(centre_file, "get_now_timestamp", return_value=timestamp):

        extra_fields_added = [
            {
                "Root Sample ID": "1",
                "RNA ID": "RNA_0043_H09",
                "plate_barcode": "RNA_0043",
                "source": "Alderley",
                "coordinate": "H09",
                "line_number": 2,
                "file_name": "ASDF_200507_1340.csv",
                "file_name_date": datetime(2020, 5, 7, 13, 40),
                "created_at": timestamp,
                "updated_at": timestamp,
                "Result": "Positive",
                "Lab ID": "Val",
            },
        ]

        with StringIO() as fake_csv:
            fake_csv.write("Root Sample ID,RNA ID,Result,Lab ID\n")
            fake_csv.write("1,RNA_0043_H09,Positive,Val\n")
            fake_csv.write("1,RNA_0043_H09,Positive,Val\n")
            fake_csv.seek(0)

            csv_to_test_reader = DictReader(fake_csv)

            augmented_data = centre_file.format_and_filter_rows(csv_to_test_reader)
            assert augmented_data == extra_fields_added

            assert centre_file.logging_collection.aggregator_types["TYPE 5"].count_errors == 1
            assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 0

# tests for required headers
def test_check_for_required_headers(config):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some file", centre)

    # empty file
    with StringIO() as fake_csv:
        csv_to_test_reader = DictReader(fake_csv)
        assert centre_file.check_for_required_headers(csv_to_test_reader) is False
        assert centre_file.logging_collection.aggregator_types["TYPE 2"].count_errors == 1
        assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 1

    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some file", centre)

    # file with incorrect headers
    with StringIO() as fake_csv:
        fake_csv.write("id,RNA ID\n")
        fake_csv.write("1,RNA_0043_\n")
        fake_csv.seek(0)

        csv_to_test_reader = DictReader(fake_csv)

        assert centre_file.check_for_required_headers(csv_to_test_reader) is False
        assert centre_file.logging_collection.aggregator_types["TYPE 2"].count_errors == 1
        assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 1

    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some file", centre)

    # file with valid headers
    with StringIO() as fake_csv:
        fake_csv.write(
            f"{FIELD_ROOT_SAMPLE_ID},{FIELD_VIRAL_PREP_ID},{FIELD_RNA_ID},{FIELD_RNA_PCR_ID},"
            f"{FIELD_RESULT},{FIELD_DATE_TESTED},{FIELD_LAB_ID}\n"
        )
        fake_csv.write("1,0100000859NBC_B07,RNA_0043,CF06BAO5_B07,Positive,today,MK\n")
        fake_csv.seek(0)

        csv_to_test_reader = DictReader(fake_csv)

        assert centre_file.check_for_required_headers(csv_to_test_reader) is True
        assert centre_file.logging_collection.aggregator_types["TYPE 2"].count_errors == 0
        assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 0

    # file with missing Lab ID header and add lab id false (default)
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("some_file.csv", centre)

    with StringIO() as fake_csv_without_lab_id:
        fake_csv_without_lab_id.write(
            f"{FIELD_ROOT_SAMPLE_ID},{FIELD_VIRAL_PREP_ID},{FIELD_RNA_ID},{FIELD_RNA_PCR_ID},"
            f"{FIELD_RESULT},{FIELD_DATE_TESTED}\n"
        )
        fake_csv_without_lab_id.write("1,0100000859NBC_B07,RNA_0043,CF06BAO5_B07,Positive,today\n")
        fake_csv_without_lab_id.seek(0)

        csv_to_test_reader = DictReader(fake_csv_without_lab_id)

        assert centre_file.check_for_required_headers(csv_to_test_reader) is False
        assert centre_file.logging_collection.aggregator_types["TYPE 2"].count_errors == 1
        assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 1

    # file with missing Lab ID header and add lab id true
    try:
        config.ADD_LAB_ID = True
        centre = Centre(config, config.CENTRES[0])
        centre_file = CentreFile("some_file.csv", centre)

        with StringIO() as fake_csv_without_lab_id:
            fake_csv_without_lab_id.write(
                f"{FIELD_ROOT_SAMPLE_ID},{FIELD_VIRAL_PREP_ID},{FIELD_RNA_ID},{FIELD_RNA_PCR_ID},"
                f"{FIELD_RESULT},{FIELD_DATE_TESTED}\n"
            )
            fake_csv_without_lab_id.write("1,0100000859NBC_B07,RNA_0043,CF06BAO5_B07,Positive,today\n")
            fake_csv_without_lab_id.seek(0)

            csv_to_test_reader = DictReader(fake_csv_without_lab_id)

            assert centre_file.check_for_required_headers(csv_to_test_reader) is True
            assert centre_file.logging_collection.aggregator_types["TYPE 2"].count_errors == 0
            assert centre_file.logging_collection.get_count_of_all_errors_and_criticals() == 0
    finally:
        config.ADD_LAB_ID = False

# tests for backing up files
def test_backup_good_file(config, tmpdir):
    with patch.dict(config.CENTRES[0], {"backups_folder": tmpdir.realpath()}):
        # create temporary success and errors folders for the files to end up in
        success_folder = tmpdir.mkdir(SUCCESSES_DIR)
        errors_folder = tmpdir.mkdir(ERRORS_DIR)

        # checks that they are empty
        assert len(success_folder.listdir()) == 0
        assert len(errors_folder.listdir()) == 0

        # configure to use the backups folder for this test
        centre = Centre(config, config.CENTRES[0])

        # create a file inside the centre download dir
        filename = "AP_sanger_report_200503_2338.csv"

        # test the backup of the file to the successes folder
        centre_file = CentreFile(filename, centre)
        centre_file.backup_file()

        assert len(success_folder.listdir()) == 1
        assert len(errors_folder.listdir()) == 0

        filename_with_timestamp = os.path.basename(success_folder.listdir()[0])
        assert filename in filename_with_timestamp

def test_backup_bad_file(config, tmpdir):
    with patch.dict(config.CENTRES[0], {"backups_folder": tmpdir.realpath()}):
        # create temporary success and errors folders for the files to end up in
        success_folder = tmpdir.mkdir(SUCCESSES_DIR)
        errors_folder = tmpdir.mkdir(ERRORS_DIR)

        # checks that they are empty
        assert len(success_folder.listdir()) == 0
        assert len(errors_folder.listdir()) == 0

        # configure to use the backups folder for this test
        centre = Centre(config, config.CENTRES[0])

        # create a file inside the centre download dir
        filename = "AP_sanger_report_200518_2132.csv"

        # test the backup of the file to the errors folder
        centre_file = CentreFile(filename, centre)
        centre_file.logging_collection.add_error("TYPE 4", "Some error happened")
        centre_file.backup_file()

        assert len(errors_folder.listdir()) == 1
        assert len(success_folder.listdir()) == 0

        filename_with_timestamp = os.path.basename(errors_folder.listdir()[0])
        assert filename in filename_with_timestamp

# tests for parsing file name date
def test_file_name_date_parses_right(config):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("AP_sanger_report_200503_2338.csv", centre)
    assert centre_file.file_name_date().year == 2020
    assert centre_file.file_name_date().month == 5
    assert centre_file.file_name_date().day == 3
    assert centre_file.file_name_date().hour == 23
    assert centre_file.file_name_date().minute == 38

    centre_file = CentreFile("AP_sanger_report_200503_2338 (2).csv", centre)
    assert centre_file.file_name_date() == None

# tests for setting file state
def test_set_state_for_file_when_file_in_black_list(config, blacklist_for_centre, testing_centres):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("AP_sanger_report_200503_2338.csv", centre)
    centre_file.set_state_for_file()

    assert centre_file.file_state == CentreFileState.FILE_IN_BLACKLIST

def test_set_state_for_file_when_never_seen_before(config, testing_centres):
    centre = Centre(config, config.CENTRES[0])
    centre_file = CentreFile("AP_sanger_report_200503_2338.csv", centre)
    centre_file.set_state_for_file()

    assert centre_file.file_state == CentreFileState.FILE_NOT_PROCESSED_YET

def test_set_state_for_file_when_in_error_folder(config, tmpdir, testing_centres):
    with patch.dict(config.CENTRES[0], {"backups_folder": tmpdir.realpath()}):
        errors_folder = tmpdir.mkdir(ERRORS_DIR)
        success_folder = tmpdir.mkdir(SUCCESSES_DIR)

        # configure to use the backups folder for this test

        centre = Centre(config, config.CENTRES[0])

        # create a backup of the file inside the errors directory as if previously processed there
        filename = "AP_sanger_report_200518_2132.csv"
        centre_file = CentreFile(filename, centre)
        centre_file.logging_collection.add_error("TYPE 4", "Some error happened")
        centre_file.backup_file()

        assert len(errors_folder.listdir()) == 1

        # check the file state again now the error version exists
        centre_file.set_state_for_file()

        assert centre_file.file_state == CentreFileState.FILE_PROCESSED_WITH_ERROR

def test_set_state_for_file_when_in_success_folder(config):
    return False

# tests for inserting docs into mlwh
def test_insert_samples_from_docs_into_mlwh(config, mlwh_connection):
    with patch('crawler.db.create_mysql_connection', return_value = 'not none'):
        centre = Centre(config, config.CENTRES[0])
        centre_file = CentreFile("some file", centre)

        docs = [
            {
                '_id': ObjectId('5f562d9931d9959b92544728'),
                FIELD_ROOT_SAMPLE_ID: 'ABC00000004',
                FIELD_RNA_ID: 'TC-rna-00000029_H11',
                FIELD_PLATE_BARCODE: 'TC-rna-00000029',
                FIELD_COORDINATE: 'H11',
                FIELD_RESULT: 'Negative',
                FIELD_DATE_TESTED: '2020-04-23 14:40:00 UTC',
                FIELD_SOURCE: 'Test Centre',
                FIELD_LAB_ID: 'TC'
            },
            {
                '_id': ObjectId('5f562d9931d9959b92544729'),
                FIELD_ROOT_SAMPLE_ID: 'ABC00000005',
                FIELD_RNA_ID: 'TC-rna-00000029_H12',
                FIELD_PLATE_BARCODE: 'TC-rna-00000029',
                FIELD_COORDINATE: 'H12',
                FIELD_RESULT: 'Positive',
                FIELD_DATE_TESTED: '2020-04-23 14:41:00 UTC',
                FIELD_SOURCE: 'Test Centre',
                FIELD_LAB_ID: 'TC'
            }
        ]

        centre_file.insert_samples_from_docs_into_mlwh(docs)

        error_count = centre_file.logging_collection.get_count_of_all_errors_and_criticals()
        error_messages = centre_file.logging_collection.get_aggregate_messages()
        assert error_count == 0, f"Should not be any errors. Actual number errors: {error_count}. Error details: {error_messages}"

        cursor = mlwh_connection.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM {config.MLWH_DB_DBNAME}.{MLWH_TABLE_NAME}")
        rows = cursor.fetchall()
        cursor.close()

        assert rows[0][MLWH_MONGODB_ID] == '5f562d9931d9959b92544728'
        assert rows[0][MLWH_ROOT_SAMPLE_ID] == 'ABC00000004'
        assert rows[0][MLWH_RNA_ID] == 'TC-rna-00000029_H11'
        assert rows[0][MLWH_PLATE_BARCODE] == 'TC-rna-00000029'
        assert rows[0][MLWH_COORDINATE] == 'H11'
        assert rows[0][MLWH_RESULT] == 'Negative'
        assert rows[0][MLWH_DATE_TESTED_STRING] == '2020-04-23 14:40:00 UTC'
        assert rows[0][MLWH_DATE_TESTED] == datetime(2020, 4, 23, 14, 40, 0)
        assert rows[0][MLWH_SOURCE] == 'Test Centre'
        assert rows[0][MLWH_LAB_ID] == 'TC'
        assert rows[0][MLWH_CREATED_AT] is not None
        assert rows[0][MLWH_UPDATED_AT] is not None

def test_insert_samples_from_docs_into_mlwh_date_tested_missing(config, mlwh_connection):
    with patch('crawler.db.create_mysql_connection', return_value = 'not none'):
        centre = Centre(config, config.CENTRES[0])
        centre_file = CentreFile("some file", centre)

        docs = [
            {
                '_id': ObjectId('5f562d9931d9959b92544728'),
                FIELD_ROOT_SAMPLE_ID: 'ABC00000004',
                FIELD_RNA_ID: 'TC-rna-00000029_H11',
                FIELD_PLATE_BARCODE: 'TC-rna-00000029',
                FIELD_COORDINATE: 'H11',
                FIELD_RESULT: 'Negative',
                FIELD_SOURCE: 'Test Centre',
                FIELD_LAB_ID: 'TC'
            }
        ]

        centre_file.insert_samples_from_docs_into_mlwh(docs)

        error_count = centre_file.logging_collection.get_count_of_all_errors_and_criticals()
        error_messages = centre_file.logging_collection.get_aggregate_messages()
        assert error_count == 0, f"Should not be any errors. Actual number errors: {error_count}. Error details: {error_messages}"

        cursor = mlwh_connection.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM {config.MLWH_DB_DBNAME}.{MLWH_TABLE_NAME}")
        rows = cursor.fetchall()
        cursor.close()

        assert rows[0][MLWH_DATE_TESTED] == None

def test_insert_samples_from_docs_into_mlwh_date_tested_blank(config, mlwh_connection):
    with patch('crawler.db.create_mysql_connection', return_value = 'not none'):
        centre = Centre(config, config.CENTRES[0])
        centre_file = CentreFile("some file", centre)

        docs = [
            {
                '_id': ObjectId('5f562d9931d9959b92544728'),
                FIELD_ROOT_SAMPLE_ID: 'ABC00000004',
                FIELD_RNA_ID: 'TC-rna-00000029_H11',
                FIELD_PLATE_BARCODE: 'TC-rna-00000029',
                FIELD_COORDINATE: 'H11',
                FIELD_RESULT: 'Negative',
                FIELD_DATE_TESTED: '',
                FIELD_SOURCE: 'Test Centre',
                FIELD_LAB_ID: 'TC'
            }
        ]

        centre_file.insert_samples_from_docs_into_mlwh(docs)

        error_count = centre_file.logging_collection.get_count_of_all_errors_and_criticals()
        error_messages = centre_file.logging_collection.get_aggregate_messages()
        assert error_count == 0, f"Should not be any errors. Actual number errors: {error_count}. Error details: {error_messages}"

        cursor = mlwh_connection.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM {config.MLWH_DB_DBNAME}.{MLWH_TABLE_NAME}")
        rows = cursor.fetchall()
        cursor.close()

        assert rows[0][MLWH_DATE_TESTED] == None