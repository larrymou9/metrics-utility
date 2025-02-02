import logging
import datetime
import pandas as pd
from dateutil.relativedelta import relativedelta

from metrics_utility.automation_controller_billing.dataframe_engine.base \
    import Base, list_dates

logger = logging.getLogger(__name__)

#######################################
# Code for building of the dataframe report based on JobhostSummary table
######################################

class DataframeJobhostSummaryUsage(Base):
    LOG_PREFIX = "[AAPBillingReport] "

    def build_dataframe(self):
        # A daily rollup dataframe
        billing_data_monthly_rollup = None

        # Get list of days of the specified month for the monthly report
        beginning_of_the_month = self.month.replace(day=1)
        end_of_the_month = beginning_of_the_month + relativedelta(months=1) - relativedelta(days=1)
        dates_list = list_dates(start_date=beginning_of_the_month,
                                end_date=end_of_the_month,
                                granularity="daily")

        for date in dates_list:
            ###############################
            # Generate the monthly dataset for report
            ###############################

            for data in self.extractor.iter_batches(date=date):
                # If the dataframe is empty, skip additional processing
                billing_data = data['job_host_summary']
                if billing_data.empty:
                    continue

                billing_data['organization_name'] = billing_data.organization_name.fillna("No organization name")
                billing_data['install_uuid'] = data['config']['install_uuid']

                # Store the original host name for mapping purposes
                billing_data['original_host_name'] = billing_data['host_name']
                if 'ansible_host_variable' in billing_data.columns:
                    # Replace missing ansible_host_variable with host name
                    billing_data['ansible_host_variable'] = billing_data.ansible_host_variable.fillna(billing_data['host_name'])
                    # And use the new ansible_host_variable instead of host_name, since
                    # what is in ansible_host_variable should be the actual host we count
                    billing_data['host_name'] = billing_data['ansible_host_variable']

                # Sumarize all task counts into 1 col
                def sum_columns(row):
                    return sum([row[i] for i in ['dark', 'failures', 'ok', 'skipped', 'ignored',  'rescued']])
                billing_data['task_runs'] = billing_data.apply(sum_columns, axis=1)

                ################################
                # Do the aggregation
                ################################
                billing_data_group = billing_data.groupby(
                    self.unique_index_columns(), dropna=False
                ).agg(
                    task_runs=('task_runs', 'sum'),
                    host_runs=('host_name', 'count'))

                # Tweak types to match the table
                billing_data_group = self.cast_dataframe(billing_data_group, self.cast_types())

                ################################
                # Merge aggregations of multiple batches
                ################################
                if billing_data_monthly_rollup is None:
                    billing_data_monthly_rollup = billing_data_group
                else:
                    # Multipart collection, merge the dataframes and sum counts
                    billing_data_monthly_rollup = pd.merge(
                        billing_data_monthly_rollup.loc[:, ],
                        billing_data_group.loc[:, ],
                        on=self.unique_index_columns(),
                        how='outer')

                    billing_data_monthly_rollup = self.summarize_merged_dataframes(
                        billing_data_monthly_rollup, self.data_columns())

                    # Tweak types to match the table
                    billing_data_monthly_rollup = self.cast_dataframe(
                        billing_data_monthly_rollup, self.cast_types())

        if billing_data_monthly_rollup is None:
            return None

        return billing_data_monthly_rollup.reset_index()

    @staticmethod
    def unique_index_columns():
        return ['organization_name', 'host_name', 'original_host_name', 'install_uuid', 'job_remote_id']

    @staticmethod
    def data_columns():
        return ['host_runs', 'task_runs']

    @staticmethod
    def cast_types():
        return {'task_runs': int, 'host_runs': int}
